"""The measurement protocol every test goes through.

check -> setup -> cool-down -> warm-up -> N measured iterations -> statistics.

A test never produces a score of zero for something it could not do. It ends
in one of the statuses below with a human-readable reason.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import stats
from .monitors import Monitor, is_throttling

OK = "ok"
INVALID = "invalid"  # ran, but results too unstable or too few to trust
SKIPPED = "skipped"  # not selected, cancelled, or experimental
INCOMPATIBLE = "incompatible"  # the software or hardware it needs is not here
ERROR = "error"  # something failed; see reason and log


class TestUnavailable(Exception):
    """Raised by check() or setup() when a test cannot run on this machine."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class Cancelled(Exception):
    pass


@dataclass
class TestSpec:
    id: str
    category: str  # "ae", "c4d", "gpu", "multitask"
    title: str
    metric: str = "seconds"  # "seconds" (lower is better) or "fps" (higher is better)
    cache: str = "warm"  # "warm" or "cold"
    iterations: int = 5
    quick_iterations: int = 3
    warmup: bool = True
    min_valid: int = 3
    quick_min_valid: Optional[int] = None
    params: Dict[str, Any] = field(default_factory=dict)
    quick_params: Dict[str, Any] = field(default_factory=dict)
    experimental: bool = False
    description: str = ""

    def resolved_params(self, quick: bool) -> Dict[str, Any]:
        p = dict(self.params)
        if quick:
            p.update(self.quick_params)
        return p

    def n_iterations(self, quick: bool) -> int:
        return self.quick_iterations if quick else self.iterations

    def needed_valid(self, quick: bool) -> int:
        if quick and self.quick_min_valid is not None:
            return self.quick_min_valid
        return min(self.min_valid, self.n_iterations(quick))


@dataclass
class Measurement:
    value: Optional[float]  # seconds or fps, per the spec's metric
    wall_s: float = 0.0
    detail: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    log: Optional[str] = None


@dataclass
class RunContext:
    platform: Any
    monitor: Monitor
    config: Any
    run_id: str
    work: Path
    logs: Path
    quick: bool = False
    apps: Dict[str, Any] = field(default_factory=dict)
    on_event: Callable[[Dict[str, Any]], None] = lambda e: None
    cancel: threading.Event = field(default_factory=threading.Event)
    admin: bool = False
    # Seconds of cool-down before each test; None uses the protocol default.
    cooldown_s: Optional[float] = None
    # Medians of finished tests, so the multitasking test can reuse isolated times.
    finished: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


class BenchTest:
    """Base class. Subclasses implement run_once and optionally check/setup/teardown."""

    def __init__(self, spec: TestSpec):
        self.spec = spec

    def check(self, ctx: RunContext) -> None:
        """Raise TestUnavailable if this machine cannot run the test."""

    def setup(self, ctx: RunContext) -> None:
        pass

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        raise NotImplementedError

    def teardown(self, ctx: RunContext) -> None:
        pass

    def extra_result(self, ctx: RunContext) -> Dict[str, Any]:
        """Anything test-specific to store next to the iterations."""
        return {}


def cooldown(ctx: RunContext, min_seconds: float, max_seconds: float = 300.0) -> Dict[str, Any]:
    """Wait at least min_seconds, then until the thermal state is nominal or fair."""
    start = time.time()
    while True:
        ctx.check_cancel()
        waited = time.time() - start
        thermal = ctx.monitor.now().thermal
        if waited >= min_seconds and thermal in (None, "nominal", "fair"):
            break
        if waited >= max_seconds:
            break
        time.sleep(2)
    return {"waited_s": round(time.time() - start, 1), "thermal_at_start": thermal}


def run_test(test: BenchTest, ctx: RunContext) -> Dict[str, Any]:
    spec = test.spec
    result: Dict[str, Any] = {
        "id": spec.id,
        "category": spec.category,
        "title": spec.title,
        "metric": spec.metric,
        "cache": spec.cache,
        "experimental": spec.experimental,
        "status": None,
        "reason": None,
        "flags": [],
        "params": spec.resolved_params(ctx.quick),
        "iterations": [],
        "warmup": None,
    }
    started = time.time()

    def finish(status: str, reason: Optional[str] = None) -> Dict[str, Any]:
        result["status"] = status
        result["reason"] = reason
        result["duration_s"] = round(time.time() - started, 1)
        ctx.on_event({"type": "test_done", "test": spec.id, "title": spec.title, "status": status,
                      "reason": reason})
        return result

    if spec.experimental:
        return finish(SKIPPED, "experimental test, not scored in this version")

    ctx.on_event({"type": "test_start", "test": spec.id, "title": spec.title})
    try:
        test.check(ctx)
        test.setup(ctx)
    except TestUnavailable as e:
        return finish(e.status, e.reason)
    except Cancelled:
        return finish(SKIPPED, "cancelled")
    except Exception as e:
        result["traceback"] = traceback.format_exc()
        return finish(ERROR, f"setup failed: {e}")

    params = spec.resolved_params(ctx.quick)
    n = spec.n_iterations(ctx.quick)
    try:
        pause = ctx.cooldown_s if ctx.cooldown_s is not None else (10 if ctx.quick else 30)
        result["cooldown"] = cooldown(ctx, min_seconds=pause)
        if spec.warmup:
            ctx.on_event({"type": "iteration", "test": spec.id, "phase": "warm-up", "i": 0, "n": n})
            w = _measure(test, ctx, params, -1)
            result["warmup"] = w
            if w.get("error"):
                return finish(ERROR, f"warm-up failed: {w['error']}")

        consecutive_errors = 0
        for i in range(n):
            ctx.check_cancel()
            ctx.on_event({"type": "iteration", "test": spec.id, "phase": "measure", "i": i + 1, "n": n})
            it = _measure(test, ctx, params, i)
            result["iterations"].append(it)
            if it.get("error"):
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    return finish(ERROR, f"two iterations in a row failed: {it['error']}")
            else:
                consecutive_errors = 0
    except Cancelled:
        return finish(SKIPPED, "cancelled")
    except TestUnavailable as e:
        return finish(e.status, e.reason)
    except Exception as e:
        result["traceback"] = traceback.format_exc()
        return finish(ERROR, str(e))
    finally:
        try:
            test.teardown(ctx)
        except Exception:
            pass

    values = [it["value"] for it in result["iterations"] if it.get("value") is not None]
    summary = stats.summarize(values, min_valid=spec.needed_valid(ctx.quick))
    result["summary"] = summary.to_dict()
    try:
        result.update(test.extra_result(ctx))
    except Exception:
        pass

    # Throttling: monitors say so, or iterations got steadily slower.
    throttled = any(is_throttling(it.get("monitor", {})) for it in result["iterations"])
    slow = summary.slowdown
    if spec.metric == "fps" and slow is not None:
        slow = -slow  # for rates, a drop is the slowdown
    if throttled:
        result["flags"].append("thermal_throttling")
    if slow is not None and slow > stats.SLOWDOWN_THRESHOLD:
        result["flags"].append("slowing_down")
    if any(it.get("cold") == "app-cold only" for it in result["iterations"]):
        result["flags"].append("app_cold_only")
    if ctx.quick:
        result["flags"].append("quick_mode")

    if not summary.valid:
        return finish(INVALID, summary.reason)
    ctx.finished[spec.id] = {"median": summary.median, "params": params}
    return finish(OK)


def _measure(test: BenchTest, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Dict[str, Any]:
    cold_note = None
    if test.spec.cache == "cold":
        cold_note = "os-cold" if (ctx.admin and ctx.platform.purge_os_cache()) else "app-cold only"
    t0 = time.time()
    try:
        m = test.run_once(ctx, params, iteration)
    except (Cancelled, TestUnavailable):
        raise
    except Exception as e:
        m = Measurement(value=None, error=f"{type(e).__name__}: {e}")
    t1 = time.time()
    rec: Dict[str, Any] = {
        "value": round(m.value, 4) if m.value is not None else None,
        "wall_s": round(m.wall_s or (t1 - t0), 3),
        "started_at": round(t0, 3),
        "monitor": ctx.monitor.summarize(t0, t1),
    }
    if m.detail:
        rec["detail"] = m.detail
    if m.error:
        rec["error"] = m.error
    if m.log:
        rec["log"] = m.log
    if cold_note:
        rec["cold"] = cold_note
    return rec
