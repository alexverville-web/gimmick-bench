"""After Effects driver: builds the benchmark project with ExtendScript and renders with aerender."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import REPO_ROOT
from ..proc import ProcResult, run_timed
from .discovery import AEInstall

SCRIPTS = REPO_ROOT / "scripts" / "ae"
ASSETS = REPO_ROOT / "assets" / "footage"
IS_MAC = sys.platform == "darwin"

# aerender prints one progress line per frame, e.g.
#   PROGRESS:  0;00;00;12 (13): 1 Seconds        (timecode display)
#   PROGRESS:  00012 (13): 1 Seconds              (frames display)
FRAME_LINE = re.compile(r"PROGRESS:\s+[\d;:]+\s+\((\d+)\)")
START_LINE = re.compile(r"Starting composition", re.I)
FINISH_LINE = re.compile(r"Finished composition", re.I)
ERROR_LINE = re.compile(r"aerender ERROR|^ERROR|After Effects error", re.I)


class AfterEffectsError(RuntimeError):
    pass


def build_fingerprint(ae: AEInstall) -> str:
    """Changes when the AE version, the build script or the footage changes."""
    h = hashlib.sha256()
    h.update((ae.version or ae.year).encode())
    for p in sorted(SCRIPTS.glob("*.jsx")):
        h.update(p.read_bytes())
    sums = ASSETS / "SHA256SUMS"
    if sums.exists():
        h.update(sums.read_bytes())
    return h.hexdigest()[:12]


def verify_assets() -> List[str]:
    """Return a list of problems with the committed footage (empty means fine)."""
    sums = ASSETS / "SHA256SUMS"
    if not sums.exists():
        return ["assets/footage/SHA256SUMS is missing"]
    problems = []
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        f = ASSETS / name.strip().lstrip("*")
        if not f.exists():
            problems.append(f"missing {f.name}")
            continue
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            problems.append(f"checksum mismatch for {f.name}")
    return problems


def parse_render_timing(lines, frames_expected: Optional[int] = None) -> Dict[str, Any]:
    """Work out how long the render itself took from timestamped aerender output.

    Preferred: time between the "Starting composition" and "Finished
    composition" lines. Those lines are English-only, so the fallback uses the
    per-frame progress lines, which look the same in every language:
    (last - first) * frames / (frames - 1). The last resort is wall time,
    which includes application start-up and is flagged as such.
    """
    start = finish = None
    frame_times = []
    errors = []
    for l in lines:
        if start is None and START_LINE.search(l.text):
            start = l.t
        if FINISH_LINE.search(l.text):
            finish = l.t
        if FRAME_LINE.search(l.text):
            frame_times.append(l.t)
        if ERROR_LINE.search(l.text):
            errors.append(l.text.strip())
    out: Dict[str, Any] = {"frames_seen": len(frame_times), "errors": errors[:5]}
    if start is not None and finish is not None and finish > start:
        out["render_s"] = finish - start
        out["method"] = "start_finish_lines"
    elif len(frame_times) >= 3:
        span = frame_times[-1] - frame_times[0]
        n = len(frame_times)
        out["render_s"] = span * n / (n - 1)
        out["method"] = "frame_lines"
    else:
        out["render_s"] = None
        out["method"] = "wall_time"
    if frames_expected is not None and frame_times and len(frame_times) < frames_expected:
        out["frames_missing"] = frames_expected - len(frame_times)
    return out


SCRIPT_PREF_SECTION = '["Main Pref Section v2"]'
SCRIPT_PREF_KEY = '"Pref_SCRIPTING_FILE_NETWORK_SECURITY"'


def ae_pref_files(install: AEInstall) -> List[Path]:
    """The preference files of this After Effects version (only exist after a first launch)."""
    if IS_MAC:
        base = Path.home() / "Library" / "Preferences" / "Adobe" / "After Effects"
    else:
        base = Path(os.environ.get("APPDATA", "")) / "Adobe" / "After Effects"
    pattern = f"{install.major}.*" if install.major else "*"
    return sorted(base.glob(f"{pattern}/Adobe After Effects * Prefs*.txt"))


def enable_script_pref(text: str) -> Optional[str]:
    """Turn on 'Allow Scripts to Write Files and Access Network'. None if already on."""
    m = re.search(re.escape(SCRIPT_PREF_KEY) + r"\s*=\s*(\d+)", text)
    if m:
        if int(m.group(1)) != 0:
            return None
        return text[:m.start(1)] + "01" + text[m.end(1):]
    i = text.find(SCRIPT_PREF_SECTION)
    if i < 0:
        return None
    eol = text.find("\n", i)
    eol = len(text) if eol < 0 else eol + 1
    nl = "\r\n" if "\r\n" in text else "\n"
    return text[:eol] + f"\t{SCRIPT_PREF_KEY} = 01{nl}" + text[eol:]


def allow_script_file_access(install: AEInstall) -> List[str]:
    """Set the scripting preference so a forgotten checkbox does not stop the benchmark.

    After Effects must be closed: it rewrites the file when it quits."""
    changed = []
    for f in ae_pref_files(install):
        try:
            raw = f.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = enable_script_pref(text)
        if new is None:
            continue
        backup = f.with_name(f.name + ".gimmick-bench.bak")
        if not backup.exists():
            backup.write_bytes(raw)
        f.write_bytes(new.encode("utf-8"))
        changed.append(str(f))
    return changed


def _running_mac_apps(process_name: str) -> List[str]:
    """Bundle paths of running apps whose executable is called process_name."""
    r = subprocess.run(["pgrep", "-x", process_name], capture_output=True, text=True)
    apps = []
    for pid in r.stdout.split():
        exe = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout.strip()
        if ".app/" in exe:
            bundle = exe[:exe.index(".app/") + 4]
            if bundle not in apps:
                apps.append(bundle)
    return apps


class AfterEffects:
    def __init__(self, install: AEInstall, work: Path, logs: Path):
        self.install = install
        self.work = work / f"ae-{(install.version or install.year).replace(' ', '_')}"
        self.work.mkdir(parents=True, exist_ok=True)
        self.logs = logs
        self.project_path = self.work / "gimmick_bench_ae.aep"
        self.manifest: Optional[Dict[str, Any]] = None

    # ---------------------------------------------------------------- scripts
    def run_script(self, script: str, job: Dict[str, Any], timeout: float = 1800) -> Dict[str, Any]:
        """Run one of our .jsx files inside After Effects and return what it wrote."""
        self.ensure_closed()
        allow_script_file_access(self.install)
        stamp = f"{script.replace('.jsx', '')}-{int(time.time() * 1000)}"
        job_path = self.work / f"{stamp}.job.json"
        done_path = self.work / f"{stamp}.done.json"
        wrapper = self.work / f"{stamp}.wrapper.jsx"
        job = dict(job, done_path=_js_path(done_path), quit=True)
        job_path.write_text(json.dumps(job), encoding="utf-8")
        wrapper.write_text(
            f'var GB_JOB_PATH = "{_js_path(job_path)}";\n'
            f'var GB_SCRIPTS_DIR = "{_js_path(SCRIPTS)}";\n'
            f'$.evalFile(GB_SCRIPTS_DIR + "/common.jsx");\n'
            f'$.evalFile(GB_SCRIPTS_DIR + "/{script}");\n',
            encoding="utf-8",
        )
        log = self.logs / f"{stamp}.log"
        if IS_MAC:
            js = f'$.evalFile(\\"{_js_path(wrapper)}\\")'
            cmd = [
                "osascript",
                "-e", f"with timeout of {int(timeout)} seconds",
                "-e", f'tell application "{self.install.app}" to DoScript "{js}"',
                "-e", "end timeout",
            ]
            proc = subprocess.Popen(cmd, stdout=open(log, "w"), stderr=subprocess.STDOUT)
        else:
            proc = subprocess.Popen([str(self.install.app), "-r", str(wrapper)],
                                    stdout=open(log, "w"), stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if done_path.exists():
                break
            if IS_MAC and proc.poll() not in (None, 0) and not done_path.exists():
                # osascript failed before the script could run (permissions, app missing).
                time.sleep(2)
                if not done_path.exists():
                    raise AfterEffectsError(
                        "Could not run a script in After Effects. Allow this app to control "
                        "After Effects (System Settings > Privacy & Security > Automation). "
                        f"Details: {log.read_text(errors='replace')[-400:]}")
            time.sleep(1)
        else:
            proc.kill()
            raise AfterEffectsError(f"After Effects did not finish {script} within {int(timeout)} s")
        time.sleep(0.5)
        try:
            payload = json.loads(done_path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise AfterEffectsError(f"Unreadable result from {script}: {e}")
        self._wait_for_quit(proc)
        if not payload.get("ok"):
            raise AfterEffectsError(f"{script} failed: {payload.get('error')}")
        return payload

    def _wait_for_quit(self, proc, timeout: float = 120) -> None:
        """Make sure the scripted AE instance has closed before aerender starts."""
        end = time.time() + timeout
        while time.time() < end:
            if not self.gui_running():
                break
            time.sleep(1)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def gui_running(self) -> bool:
        if IS_MAC:
            r = subprocess.run(["pgrep", "-x", "After Effects"], capture_output=True)
            return r.returncode == 0
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AfterFX.exe", "/NH"],
                           capture_output=True, text=True)
        return "AfterFX.exe" in r.stdout

    def ensure_closed(self, timeout: float = 90) -> None:
        """Ask any open After Effects to quit, the same way as Cmd+Q / closing the window.

        It still asks about unsaved work; nothing is force-killed."""
        if not self.gui_running():
            return
        if IS_MAC:
            for app in _running_mac_apps("After Effects"):
                subprocess.run(["osascript", "-e", f'tell application "{app}" to quit'],
                               capture_output=True, timeout=60)
        else:
            subprocess.run(["taskkill", "/IM", "AfterFX.exe"], capture_output=True)
        end = time.time() + timeout
        while time.time() < end:
            if not self.gui_running():
                time.sleep(3)  # let it release its files and licence
                return
            time.sleep(1)
        raise AfterEffectsError(
            "After Effects is open and did not quit (it may be asking to save a project). "
            "Quit it, then start the benchmark again.")

    # ---------------------------------------------------------------- project
    def ensure_project(self) -> Dict[str, Any]:
        """Build the benchmark project unless an identical one already exists."""
        fp = build_fingerprint(self.install)
        manifest_path = self.work / "manifest.json"
        if self.project_path.exists() and manifest_path.exists():
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fp:
                self.manifest = cached
                return cached
        problems = verify_assets()
        if problems:
            raise AfterEffectsError("Benchmark footage is damaged: " + "; ".join(problems))
        render_dir = self.work / "render"
        render_dir.mkdir(exist_ok=True)
        job = {
            "assets_dir": _js_path(ASSETS),
            "project_path": _js_path(self.project_path),
            "render_dir": _js_path(render_dir),
        }
        try:
            payload = self.run_script("build_project.jsx", job, timeout=1800)
        except AfterEffectsError:
            # After Effects sometimes fails on its first scripted launch (licence check,
            # first-run dialogs). One clean retry before giving up on every AE test.
            payload = self.run_script("build_project.jsx", job, timeout=1800)
        manifest = payload["manifest"]
        manifest["fingerprint"] = fp
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.manifest = manifest
        return manifest

    def output_for(self, comp: str) -> Dict[str, Any]:
        for rq in (self.manifest or {}).get("render_queue", []):
            if rq.get("comp") == comp:
                return rq
        raise AfterEffectsError(f"{comp} is not in the render queue of the built project")

    # ---------------------------------------------------------------- render
    def render(self, comp: str, start: int, end: int, mfr: bool, tag: str) -> Dict[str, Any]:
        rq = self.output_for(comp)
        out_dir = self.work / "render" / tag
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True)
        ext = rq.get("output_extension", "jpg")
        if rq.get("kind") == "jpeg":
            target = out_dir / f"{comp}_[#####].{ext}"
        else:
            target = out_dir / f"{comp}.{ext}"
        cmd = [
            str(self.install.aerender),
            "-project", str(self.project_path),
            "-comp", comp,
            "-s", str(start), "-e", str(end),
            "-mfr", "ON" if mfr else "OFF", "100",
            "-mem_usage", "50", "90",
            "-output", str(target),
            "-v", "ERRORS_AND_PROGRESS",
            "-sound", "OFF",
        ]
        log = self.logs / f"aerender-{tag}.log"
        frames = end - start + 1
        res: ProcResult = run_timed(cmd, timeout=max(1800, frames * 60), log_path=log)
        timing = parse_render_timing(res.lines, frames)
        out_files = [p for p in out_dir.iterdir() if p.is_file()]
        detail = {
            "wall_s": round(res.wall_s, 3),
            "timing_method": timing["method"],
            "frames": frames,
            "frames_seen": timing["frames_seen"],
            "mfr": mfr,
            "output_files": len(out_files),
            "output_bytes": sum(p.stat().st_size for p in out_files),
        }
        error = None
        if res.timed_out:
            error = "aerender timed out"
        elif res.returncode not in (0, None):
            error = f"aerender exited with code {res.returncode}: " + "; ".join(timing["errors"] or [res.output[-300:]])
        elif not out_files:
            error = "aerender produced no output"
        elif rq.get("kind") == "jpeg" and len(out_files) < frames:
            error = f"rendered {len(out_files)} of {frames} frames"
        render_s = timing["render_s"] if timing["render_s"] is not None else res.wall_s
        shutil.rmtree(out_dir, ignore_errors=True)
        return {"seconds": render_s, "detail": detail, "error": error, "log": str(log)}

    def time_open(self, opens: int) -> Dict[str, Any]:
        return self.run_script("open_project.jsx", {
            "project_path": _js_path(self.project_path), "opens": opens,
        }, timeout=900)


def _js_path(p: Path) -> str:
    """Forward-slash path safe to embed in a JavaScript string."""
    return str(p).replace("\\", "/").replace('"', '\\"')
