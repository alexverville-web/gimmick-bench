"""Cinema 4D tests (Standard renderer on CPU, Octane on GPU)."""
from __future__ import annotations

from typing import Any, Dict, List

from .. import stats
from ..apps.cinema4d import Cinema4D, Cinema4DError
from ..apps.discovery import pick
from ..protocol import (BenchTest, ERROR, INCOMPATIBLE, Measurement, RunContext, TestSpec,
                        TestUnavailable)

SPECS: List[TestSpec] = [
    TestSpec("c4d.load_cold", "c4d", "Scene load, first load in a fresh process",
             cache="cold", warmup=False,
             description="About 4 million baked polygons with 4K textures, loaded by a fresh c4dpy process.",
             params=dict(scene="heavy_load", mode="load", loads=1)),
    TestSpec("c4d.load_warm", "c4d", "Scene load, repeated",
             description="Median of the second and third load of the same scene in one process.",
             params=dict(scene="heavy_load", mode="load", loads=3)),
    TestSpec("c4d.geometry", "c4d", "Geometry-heavy processing",
             description="Subdivision surfaces over animated deformers, booleans and sweeps rebuilt every frame.",
             params=dict(scene="geometry", mode="eval", start=0, end=119),
             quick_params=dict(end=59)),
    TestSpec("c4d.mograph", "c4d", "Cloners and procedural geometry",
             description="10,800-clone grid and nested radial cloners with Formula and Random effectors, Voronoi fracture.",
             params=dict(scene="mograph", mode="eval", start=0, end=119),
             quick_params=dict(end=59)),
    TestSpec("c4d.anim", "c4d", "Animation and simulation evaluation",
             description="400 rigid bodies falling on a collider, plus a deformer stack on a dense mesh, stepped frame by frame.",
             params=dict(scene="anim", mode="eval", start=0, end=149),
             quick_params=dict(end=74)),
    TestSpec("c4d.cpu_render", "c4d", "CPU rendering (Standard renderer)",
             description="1920x1080, best antialiasing, area shadows, ambient occlusion and global illumination.",
             params=dict(scene="render_standard", mode="render", start=0, end=9),
             quick_params=dict(end=3)),
    TestSpec("gpu.octane", "gpu", "GPU rendering (Octane)",
             description="The same shot rendered with Octane at the plugin's default settings. Scored separately.",
             params=dict(scene="render_octane", mode="render", start=0, end=9),
             quick_params=dict(end=3)),
    TestSpec("c4d.viewport", "c4d", "Viewport playback",
             experimental=True,
             description="Not measurable reliably: c4dpy has no viewport. Kept as a placeholder, never scored."),
]


def get_c4d(ctx: RunContext) -> Cinema4D:
    if "c4d_driver" in ctx.apps:
        drv = ctx.apps["c4d_driver"]
        if isinstance(drv, Exception):
            raise drv
        return drv
    install = pick(ctx.apps.get("c4d_installs", []), ctx.apps.get("c4d_wanted"))
    if install is None:
        err = TestUnavailable(INCOMPATIBLE, "Cinema 4D 2024 or later is not installed")
        ctx.apps["c4d_driver"] = err
        raise err
    drv = Cinema4D(install, ctx.work, ctx.logs)
    ctx.on_event({"type": "status", "message": f"Building the Cinema 4D scenes in {install.year}"})
    try:
        ctx.apps["c4d_probe"] = drv.probe()
        manifest = drv.ensure_scenes()
    except Cinema4DError as e:
        err = TestUnavailable(ERROR, f"Could not prepare Cinema 4D: {e}")
        ctx.apps["c4d_driver"] = err
        raise err
    ctx.apps["c4d_driver"] = drv
    ctx.apps["c4d_manifest"] = manifest
    return drv


class C4DTest(BenchTest):
    def setup(self, ctx: RunContext) -> None:
        self.c4d = get_c4d(ctx)
        key = self.spec.params["scene"]
        if key == "render_octane" and not (ctx.apps.get("c4d_probe") or {}).get("octane_available"):
            raise TestUnavailable(INCOMPATIBLE, "Octane is not installed or not licensed in this Cinema 4D")
        try:
            self.scene_path = self.c4d.scene(key)
        except Cinema4DError as e:
            raise TestUnavailable(ERROR, str(e))
        self.use_commandline = False

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        job = {k: v for k, v in params.items() if k != "scene"}
        job["scene"] = self.scene_path
        if self.use_commandline:
            return self._commandline(params, iteration)
        try:
            r = self.c4d.run_job("bench_c4d.py", job)
        except Cinema4DError as e:
            if self.spec.id == "gpu.octane" and iteration == -1:
                # RenderDocument may not drive Octane headless; fall back to Commandline once.
                self.use_commandline = True
                return self._commandline(params, iteration)
            return Measurement(value=None, error=str(e))
        detail = {"c4dpy_wall_s": round(r["_wall_s"], 2)}
        if params["mode"] == "load":
            loads = r["loads_s"]
            detail["loads_s"] = loads
            value = loads[0] if self.spec.id == "c4d.load_cold" else stats.median(loads[1:] or loads)
        else:
            value = r["seconds"]
            for k in ("frames", "fps", "frame_times_s", "engine", "resolution"):
                if k in r:
                    detail[k] = r[k]
        return Measurement(value=value, wall_s=r["_wall_s"], detail=detail, log=r["_log"])

    def _commandline(self, params, iteration) -> Measurement:
        tag = f"{self.spec.id}-{iteration}"
        r = self.c4d.commandline_render(self.scene_path, params["start"], params["end"], tag)
        r["detail"]["via"] = "Commandline"
        return Measurement(value=None if r["error"] else r["seconds"], detail=r["detail"],
                           error=r["error"], log=r["log"])

    def extra_result(self, ctx: RunContext) -> Dict[str, Any]:
        out: Dict[str, Any] = {"app": {"name": "Cinema 4D", "version": self.c4d.install.version}}
        if self.spec.id == "gpu.octane":
            out["app"]["octane"] = (ctx.apps.get("c4d_probe") or {}).get("octane_name")
            if self.use_commandline:
                out.setdefault("notes", []).append("rendered through Commandline; time parsed from its log")
        return out


class C4DPlaceholder(BenchTest):
    def run_once(self, ctx, params, iteration):  # never called: experimental tests are skipped
        raise NotImplementedError


def build_tests() -> List[BenchTest]:
    return [C4DPlaceholder(s) if s.experimental else C4DTest(s) for s in SPECS]
