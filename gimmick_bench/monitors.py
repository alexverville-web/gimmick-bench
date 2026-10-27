"""Background sampling of thermal state, memory and load while tests run."""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from .platform import Platform, Sample

THERMAL_ORDER = ["nominal", "fair", "serious", "critical"]


class Monitor:
    def __init__(self, platform: Platform, interval: float = 2.0):
        self.platform = platform
        self.interval = interval
        self.samples: List[Sample] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> "Monitor":
        self._thread = threading.Thread(target=self._loop, name="monitor", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                s = self.platform.sample()
            except Exception:  # a failed sample must never stop a benchmark
                s = Sample(t=time.time())
            with self._lock:
                self.samples.append(s)
            self._stop.wait(self.interval)

    def now(self) -> Sample:
        try:
            return self.platform.sample()
        except Exception:
            return Sample(t=time.time())

    def window(self, t0: float, t1: float) -> List[Sample]:
        with self._lock:
            return [s for s in self.samples if t0 <= s.t <= t1]

    def summarize(self, t0: float, t1: float) -> Dict:
        return summarize_samples(self.window(t0, t1))

    def latest_thermal(self) -> Optional[str]:
        with self._lock:
            for s in reversed(self.samples):
                if s.thermal:
                    return s.thermal
        return None


def worst_thermal(states) -> Optional[str]:
    ranked = [THERMAL_ORDER.index(s) for s in states if s in THERMAL_ORDER]
    return THERMAL_ORDER[max(ranked)] if ranked else None


def summarize_samples(samples: List[Sample]) -> Dict:
    if not samples:
        return {"samples": 0}

    def vals(attr):
        return [getattr(s, attr) for s in samples if getattr(s, attr) is not None]

    out: Dict = {"samples": len(samples)}
    th = worst_thermal(vals("thermal"))
    if th:
        out["thermal_max"] = th
    limits = vals("cpu_speed_limit")
    if limits:
        out["cpu_speed_limit_min"] = min(limits)
    for attr, key, fn in [
        ("swap_used_gb", "swap_peak_gb", max),
        ("compressed_gb", "compressed_peak_gb", max),
        ("mem_free_pct", "mem_free_min_pct", min),
        ("load_avg", "load_avg_max", max),
        ("cpu_busy", "cpu_busy_max", max),
        ("gpu_temp_c", "gpu_temp_max_c", max),
    ]:
        v = vals(attr)
        if v:
            out[key] = round(fn(v), 2)
    if any(vals("gpu_throttle")):
        out["gpu_throttled"] = True
    return out


def is_throttling(summary: Dict) -> bool:
    if summary.get("thermal_max") in ("serious", "critical"):
        return True
    if summary.get("cpu_speed_limit_min") is not None and summary["cpu_speed_limit_min"] < 100:
        return True
    return bool(summary.get("gpu_throttled"))
