"""After Effects tests."""
from __future__ import annotations

from typing import Any, Dict, List

from .. import stats
from ..apps.aftereffects import AfterEffects, AfterEffectsError
from ..apps.discovery import pick
from ..protocol import (BenchTest, ERROR, INCOMPATIBLE, Measurement, RunContext, TestSpec,
                        TestUnavailable)


def _frames(start: int, end: int) -> Dict[str, int]:
    return {"start": start, "end": end}


SPECS: List[TestSpec] = [
    TestSpec("ae.shapes", "ae", "Heavy 2D shape animation",
             description="300+ animated shape layers with repeaters, trim and offset paths, precomps, motion blur. MFR off.",
             params=dict(comp="BENCH_shapes", mfr=False, **_frames(0, 119)),
             quick_params=_frames(0, 59)),
    TestSpec("ae.expressions", "ae", "Expressions and procedural animation",
             description="160 expression-driven layers (wiggle, sampleImage, valueAtTime chains, loopOut) and 40 live text layers. MFR off.",
             params=dict(comp="BENCH_expressions", mfr=False, **_frames(0, 119)),
             quick_params=_frames(0, 59)),
    TestSpec("ae.mixed_4k", "ae", "4K mixed-media composition",
             description="4K H.264 and ProRes footage, masks, track matte, typography, precomps, grading and grain. MFR on.",
             params=dict(comp="BENCH_mixed_4k", mfr=True, **_frames(0, 149)),
             quick_params=_frames(0, 74)),
    TestSpec("ae.effects", "ae", "Heavy effects and compositing",
             description="Turbulent Displace, Fractal Noise, Gaussian blur, Glow, Camera Lens Blur, Light Rays, Lumetri, grain. MFR on.",
             params=dict(comp="BENCH_effects", mfr=True, **_frames(0, 89)),
             quick_params=_frames(0, 44)),
    TestSpec("ae.mfr_scaling", "ae", "Multi-Frame Rendering scaling",
             description="The 4K mixed-media comp with MFR off. Speed-up = MFR-off time / MFR-on time from ae.mixed_4k.",
             params=dict(comp="BENCH_mixed_4k", mfr=False, **_frames(0, 149)),
             quick_params=_frames(0, 74)),
    TestSpec("ae.preview", "ae", "Preview throughput (stands in for RAM preview)",
             metric="fps",
             description="The effects comp at half resolution, draft quality. Frames per second. Not a real RAM preview: AE cannot time one by script.",
             params=dict(comp="BENCH_preview", mfr=True, **_frames(0, 89)),
             quick_params=_frames(0, 44)),
    TestSpec("ae.export_prores", "ae", "Final export to ProRes",
             description="The 4K mixed-media comp exported to a QuickTime ProRes file, encode included.",
             params=dict(comp="BENCH_export_prores", mfr=True, **_frames(0, 149)),
             quick_params=_frames(0, 74)),
    TestSpec("ae.export_h264", "ae", "Final export to H.264",
             description="The 4K mixed-media comp exported to H.264, encode included.",
             params=dict(comp="BENCH_export_h264", mfr=True, **_frames(0, 149)),
             quick_params=_frames(0, 74)),
    TestSpec("ae.open_cold", "ae", "Project open, first open after launch",
             cache="cold", warmup=False,
             description="Fresh After Effects launch, then time app.open() of the benchmark project.",
             params=dict(opens=3)),
    TestSpec("ae.open_warm", "ae", "Project open, repeated",
             description="Median of the second and third open in the same session.",
             warmup=False, params=dict(opens=3)),
]


def get_ae(ctx: RunContext) -> AfterEffects:
    """Find After Effects and build the project once per run, shared by all AE tests."""
    if "ae_driver" in ctx.apps:
        drv = ctx.apps["ae_driver"]
        if isinstance(drv, Exception):
            raise drv
        return drv
    install = pick(ctx.apps.get("ae_installs", []), ctx.apps.get("ae_wanted"))
    if install is None:
        err = TestUnavailable(INCOMPATIBLE, "After Effects 2025 or later is not installed")
        ctx.apps["ae_driver"] = err
        raise err
    drv = AfterEffects(install, ctx.work, ctx.logs)
    ctx.on_event({"type": "status", "message": f"Building the After Effects project in {install.year}"})
    try:
        manifest = drv.ensure_project()
    except AfterEffectsError as e:
        err = TestUnavailable(ERROR, f"Could not build the After Effects project: {e}")
        ctx.apps["ae_driver"] = err
        raise err
    ctx.apps["ae_driver"] = drv
    ctx.apps["ae_manifest"] = manifest
    return drv


class AeRenderTest(BenchTest):
    def setup(self, ctx: RunContext) -> None:
        self.ae = get_ae(ctx)
        self.ae.output_for(self.spec.params["comp"])

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        tag = f"{self.spec.id}-{iteration if iteration >= 0 else 'warmup'}"
        r = self.ae.render(params["comp"], params["start"], params["end"], params["mfr"], tag)
        seconds = r["seconds"]
        value = seconds
        if self.spec.metric == "fps" and seconds:
            value = (params["end"] - params["start"] + 1) / seconds
        detail = r["detail"]
        if detail.get("timing_method") == "wall_time":
            detail["note"] = "timed including After Effects start-up"
        return Measurement(value=value if not r["error"] else None, wall_s=detail["wall_s"],
                           detail=detail, error=r["error"], log=r["log"])

    def extra_result(self, ctx: RunContext) -> Dict[str, Any]:
        out: Dict[str, Any] = {"app": {"name": "After Effects", "version": self.ae.install.version}}
        return out


class AeMfrScalingTest(AeRenderTest):
    def extra_result(self, ctx: RunContext) -> Dict[str, Any]:
        # The speed-up itself is computed by the scoring engine from both medians,
        # so it can be recalculated from raw data; we store the pairing here.
        out = super().extra_result(ctx)
        on = ctx.finished.get("ae.mixed_4k")
        if on and on.get("median"):
            out["mfr_on_median_s"] = on["median"]
        return out


class AeOpenTest(BenchTest):
    def setup(self, ctx: RunContext) -> None:
        self.ae = get_ae(ctx)

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        try:
            r = self.ae.time_open(params["opens"])
        except AfterEffectsError as e:
            return Measurement(value=None, error=str(e))
        opens = r.get("opens_s") or []
        if not opens:
            return Measurement(value=None, error="no open timings returned")
        if self.spec.id == "ae.open_cold":
            value = opens[0]
        else:
            warm = opens[1:]
            value = stats.median(warm) if warm else None
        return Measurement(value=value, detail={"opens_s": opens})


def build_tests() -> List[BenchTest]:
    tests: List[BenchTest] = []
    for spec in SPECS:
        if spec.id.startswith("ae.open"):
            tests.append(AeOpenTest(spec))
        elif spec.id == "ae.mfr_scaling":
            tests.append(AeMfrScalingTest(spec))
        else:
            tests.append(AeRenderTest(spec))
    return tests
