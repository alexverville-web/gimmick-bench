"""Multitasking test: After Effects and Cinema 4D at once, with a fixed memory ballast.

Each job is timed inside its own process (aerender's progress lines, c4dpy's
perf_counter), exactly as in the isolated tests, so the two can be compared:

  retention = mean over jobs of (isolated time / time under load)

The scored value is the slower of the two jobs under load. Start-up of the
two processes is not perfectly simultaneous, so the overlap of the two render
windows is recorded too.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Any, Dict, List

from ..config import REPO_ROOT
from ..protocol import (BenchTest, INCOMPATIBLE, Measurement, RunContext, TestSpec,
                        TestUnavailable)
from .ae import SPECS as AE_SPECS, get_ae
from .c4d import SPECS as C4D_SPECS, get_c4d

AE_JOB = next(s for s in AE_SPECS if s.id == "ae.mixed_4k")
C4D_JOB = next(s for s in C4D_SPECS if s.id == "c4d.cpu_render")

SPECS: List[TestSpec] = [
    TestSpec("mt.ae_c4d_ballast", "multitask", "After Effects + Cinema 4D + 8 GB of other apps",
             iterations=3, quick_iterations=1, min_valid=3, quick_min_valid=1, warmup=False,
             description="ae.mixed_4k (MFR on) and c4d.cpu_render run at the same time while a fixed memory "
                         "ballast stands in for Photoshop, Illustrator and a browser."),
]


class Ballast:
    def __init__(self, gb: float):
        self.gb = gb
        self.proc = None

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gimmick_bench.ballast", str(self.gb)],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        line = self.proc.stdout.readline() if self.proc.stdout else ""
        if "ready" not in line:
            self.__exit__()
            raise RuntimeError(f"memory ballast of {self.gb} GB could not be allocated")
        return self

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


class MultitaskTest(BenchTest):
    def setup(self, ctx: RunContext) -> None:
        try:
            self.ae = get_ae(ctx)
            self.c4d = get_c4d(ctx)
        except TestUnavailable as e:
            raise TestUnavailable(INCOMPATIBLE if e.status == INCOMPATIBLE else e.status,
                                  f"needs both After Effects and Cinema 4D ({e.reason})")
        self.ae_params = AE_JOB.resolved_params(ctx.quick)
        self.c4d_params = C4D_JOB.resolved_params(ctx.quick)
        self.c4d_scene = self.c4d.scene(self.c4d_params["scene"])
        self.isolated = {
            "ae": (ctx.finished.get(AE_JOB.id) or {}).get("median"),
            "c4d": (ctx.finished.get(C4D_JOB.id) or {}).get("median"),
        }

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        results: Dict[str, Any] = {}

        def ae_job():
            t = time.time()
            p = self.ae_params
            r = self.ae.render(p["comp"], p["start"], p["end"], p["mfr"], f"mt-ae-{iteration}")
            results["ae"] = dict(r, started=t, ended=time.time())

        def c4d_job():
            t = time.time()
            job = {k: v for k, v in self.c4d_params.items() if k != "scene"}
            job["scene"] = self.c4d_scene
            try:
                r = self.c4d.run_job("bench_c4d.py", job)
                results["c4d"] = {"seconds": r["seconds"], "error": None, "started": t, "ended": time.time(),
                                  "wall_s": r["_wall_s"]}
            except Exception as e:
                results["c4d"] = {"seconds": None, "error": str(e), "started": t, "ended": time.time()}

        with Ballast(ctx.config.ballast_gb):
            threads = [threading.Thread(target=ae_job), threading.Thread(target=c4d_job)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        errors = [f"{k}: {v['error']}" for k, v in results.items() if v.get("error")]
        if errors:
            return Measurement(value=None, error="; ".join(errors))
        ae_s, c4d_s = results["ae"]["seconds"], results["c4d"]["seconds"]
        overlap = max(0.0, min(results["ae"]["ended"], results["c4d"]["ended"]) -
                      max(results["ae"]["started"], results["c4d"]["started"]))
        span = max(results["ae"]["ended"], results["c4d"]["ended"]) - min(results["ae"]["started"], results["c4d"]["started"])
        detail: Dict[str, Any] = {
            "ae_s": round(ae_s, 3), "c4d_s": round(c4d_s, 3),
            "overlap_fraction": round(overlap / span, 3) if span else None,
            "ballast_gb": ctx.config.ballast_gb,
        }
        ratios = []
        for key, under_load in (("ae", ae_s), ("c4d", c4d_s)):
            iso = self.isolated.get(key)
            if iso and under_load:
                ratios.append(iso / under_load)
                detail[f"{key}_isolated_s"] = round(iso, 3)
        if len(ratios) == 2:
            detail["retention"] = round(sum(ratios) / 2, 4)
        return Measurement(value=max(ae_s, c4d_s), detail=detail)

    def extra_result(self, ctx: RunContext) -> Dict[str, Any]:
        return {"isolated_medians_s": self.isolated, "workloads": [AE_JOB.id, C4D_JOB.id],
                "notes": ["Other creative apps are represented by the memory ballast, not opened."]}


def build_tests() -> List[BenchTest]:
    return [MultitaskTest(s) for s in SPECS]
