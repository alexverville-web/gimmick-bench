"""Cinema 4D driver: builds scenes and times workloads through c4dpy; Commandline as a fallback for Octane."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import REPO_ROOT
from .staging import staged
from ..proc import run_timed
from .discovery import C4DInstall, _exe

SCRIPTS = REPO_ROOT / "scripts" / "c4d"
ASSETS = REPO_ROOT / "assets" / "footage"

LICENSE_HINT = re.compile(r"login|license|licence|Maxon App|user name|password", re.I)
CMD_SUCCESS = re.compile(r"Rendering successful:\s*([\d.]+)\s*sec", re.I)
CMD_FRAME = re.compile(r"Rendering frame\s+(\d+)", re.I)


class Cinema4DError(RuntimeError):
    pass


def build_fingerprint(inst: C4DInstall) -> str:
    h = hashlib.sha256()
    h.update((inst.version or inst.year).encode())
    for p in sorted(SCRIPTS.glob("*.py")):
        h.update(p.read_bytes())
    sums = ASSETS / "SHA256SUMS"
    if sums.exists():
        h.update(sums.read_bytes())
    return h.hexdigest()[:12]


def parse_commandline_timing(lines) -> Dict[str, Any]:
    """Render time from Commandline output, excluding start-up and licensing."""
    total = None
    frames = []
    for l in lines:
        m = CMD_SUCCESS.search(l.text)
        if m:
            total = float(m.group(1))
        if CMD_FRAME.search(l.text):
            frames.append(l.t)
    if total is not None:
        return {"render_s": total, "method": "rendering_successful_line", "frames_seen": len(frames)}
    if len(frames) >= 2 and lines:
        # From the first "Rendering frame" line to the end of output.
        return {"render_s": lines[-1].t - frames[0], "method": "frame_lines", "frames_seen": len(frames)}
    return {"render_s": None, "method": "wall_time", "frames_seen": len(frames)}


class Cinema4D:
    def __init__(self, install: C4DInstall, work: Path, logs: Path):
        self.install = install
        self.work = work / f"c4d-{(install.version or install.year).replace(' ', '_')}"
        self.work.mkdir(parents=True, exist_ok=True)
        self.logs = logs
        self.manifest: Optional[Dict[str, Any]] = None
        self._c4dpy = _exe(install.c4dpy) if install.c4dpy else None
        self._cmdline = _exe(install.commandline) if install.commandline else None

    def run_job(self, script: str, job: Dict[str, Any], timeout: float = 3600) -> Dict[str, Any]:
        if not self._c4dpy:
            raise Cinema4DError("c4dpy not found")
        stamp = f"{job.get('mode', 'build')}-{int(time.time() * 1000)}"
        job_path = self.work / f"{stamp}.job.json"
        done_path = self.work / f"{stamp}.done.json"
        job = dict(job, done_path=str(done_path))
        job_path.write_text(json.dumps(job), encoding="utf-8")
        env = dict(os.environ, GB_JOB=str(job_path))
        log = self.logs / f"c4dpy-{stamp}.log"
        res = run_timed([str(self._c4dpy), str(staged(SCRIPTS, "c4d-scripts") / script)], timeout=timeout, env=env, log_path=log)
        if not done_path.exists():
            text = res.output[-600:]
            if LICENSE_HINT.search(text):
                raise Cinema4DError(
                    "c4dpy needs a one-time login on this computer. Open c4dpy once from the Cinema 4D "
                    "folder, sign in with the Maxon App, then run the benchmark again.")
            if res.timed_out:
                raise Cinema4DError(f"c4dpy did not finish within {int(timeout)} s")
            raise Cinema4DError(f"c4dpy exited (code {res.returncode}) without a result. Log: {log}")
        payload = json.loads(done_path.read_text(encoding="utf-8"))
        payload["_wall_s"] = res.wall_s
        payload["_log"] = str(log)
        if not payload.get("ok"):
            raise Cinema4DError(payload.get("error", "unknown c4dpy error").splitlines()[0])
        return payload

    def probe(self) -> Dict[str, Any]:
        return self.run_job("bench_c4d.py", {"mode": "probe"}, timeout=600)

    def ensure_scenes(self) -> Dict[str, Any]:
        fp = build_fingerprint(self.install)
        manifest_path = self.work / "manifest.json"
        if manifest_path.exists():
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fp and all(
                    Path(s["path"]).exists() for s in cached.get("scenes", {}).values()):
                self.manifest = cached
                return cached
        scenes_dir = self.work / "scenes"
        scenes_dir.mkdir(exist_ok=True)
        payload = self.run_job("build_scenes.py", {
            "out_dir": str(scenes_dir), "assets_dir": str(staged(ASSETS, "footage")),
        }, timeout=3600)
        payload["fingerprint"] = fp
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.manifest = payload
        return payload

    def scene(self, key: str) -> str:
        scenes = (self.manifest or {}).get("scenes", {})
        if key not in scenes:
            raise Cinema4DError(f"scene '{key}' was not built")
        return scenes[key]["path"]

    def commandline_render(self, scene: str, start: int, end: int, tag: str) -> Dict[str, Any]:
        """Render through the Commandline renderer (used when RenderDocument cannot drive Octane)."""
        exe = self._cmdline or _exe(self.install.app)
        out_dir = self.work / "render" / tag
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        cmd = [str(exe), "-nogui", "-render", scene, "-frame", str(start), str(end),
               "-oimage", str(out_dir / "frame"), "-oformat", "PNG"]
        log = self.logs / f"commandline-{tag}.log"
        res = run_timed(cmd, timeout=7200, log_path=log)
        timing = parse_commandline_timing(res.lines)
        files = [p for p in out_dir.iterdir() if p.is_file()]
        shutil.rmtree(out_dir, ignore_errors=True)
        error = None
        if res.timed_out:
            error = "Commandline render timed out"
        elif not files:
            error = f"Commandline produced no images (exit code {res.returncode})"
        seconds = timing["render_s"] if timing["render_s"] is not None else res.wall_s
        return {"seconds": seconds, "error": error, "log": str(log),
                "detail": {"wall_s": round(res.wall_s, 3), "timing_method": timing["method"],
                           "frames_seen": timing["frames_seen"], "images": len(files)}}
