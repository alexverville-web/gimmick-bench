"""Runs a full or partial benchmark and writes one raw result file."""
from __future__ import annotations

import json
import os
import platform as pyplatform
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import RESULT_SCHEMA, SUITE_VERSION
from .apps import discovery
from .config import Config, logs_dir, results_dir, work_dir
from .monitors import Monitor
from .platform import get_platform
from .protocol import RunContext, run_test
from .suites import ae as ae_suite, c4d as c4d_suite, multitask as mt_suite, simulated

SUITES = ("ae", "c4d", "gpu", "multitask")
IDLE_CPU = 0.15  # whole-machine CPU use considered idle


def all_specs():
    return ae_suite.SPECS + c4d_suite.SPECS + mt_suite.SPECS


def build_tests(suites, only_ids: Optional[List[str]], simulate: bool):
    if simulate:
        tests = simulated.wrap([s for s in all_specs() if not s.experimental])
    else:
        tests = ae_suite.build_tests() + c4d_suite.build_tests() + mt_suite.build_tests()
    picked = []
    for t in tests:
        if only_ids and t.spec.id not in only_ids:
            continue
        if t.spec.category not in suites and not only_ids:
            continue
        picked.append(t)
    return picked


def detect_apps(platform, cfg: Config) -> Dict[str, Any]:
    ae = discovery.find_after_effects(platform, cfg.ae_path)
    c4d = discovery.find_cinema4d(platform, cfg.c4d_path)
    return {"ae_installs": ae, "c4d_installs": c4d}


def software_summary(apps: Dict[str, Any]) -> Dict[str, Any]:
    ae = discovery.pick(apps.get("ae_installs", []), apps.get("ae_wanted"))
    c4d = discovery.pick(apps.get("c4d_installs", []), apps.get("c4d_wanted"))
    probe = apps.get("c4d_probe") or {}
    return {
        "after_effects": ae.version if ae else None,
        "after_effects_year": ae.year if ae else None,
        "cinema4d": c4d.version if c4d else None,
        "cinema4d_year": c4d.year if c4d else None,
        "octane": probe.get("octane_name") if probe.get("octane_available") else None,
        "octane_plugin_dirs": c4d.octane_candidates if c4d else [],
        "installed": {
            "after_effects": [i.to_dict() for i in apps.get("ae_installs", [])],
            "cinema4d": [i.to_dict() for i in apps.get("c4d_installs", [])],
        },
        "python": sys.version.split()[0],
    }


def preflight(platform, monitor: Monitor, cfg: Config, quick: bool, on_event) -> Dict[str, Any]:
    out: Dict[str, Any] = {"flags": []}
    out["on_ac_power"] = platform.on_ac_power()
    if out["on_ac_power"] is False:
        out["flags"].append("on_battery")
    free = shutil.disk_usage(str(work_dir())).free / 1024 ** 3
    out["free_disk_gb"] = round(free, 1)
    if free < 20:
        raise RuntimeError(f"Only {free:.0f} GB free on the work disk; the benchmark needs at least 20 GB.")
    if free < cfg.min_free_gb:
        out["flags"].append("low_disk_space")
    out["admin"] = platform.is_admin()

    # Wait for the machine to go quiet so background work does not skew the first tests.
    limit = 180 if quick else 600
    start = time.time()
    cpu = None
    while True:
        s1 = platform.sample()
        time.sleep(3)
        s2 = platform.sample()
        cpu = s2.cpu_busy
        if cpu is None and s2.load_avg is not None:
            cpu = s2.load_avg / (os.cpu_count() or 1)
        if cpu is None or cpu < IDLE_CPU or time.time() - start > limit:
            break
        on_event({"type": "status", "message": f"Waiting for the computer to be idle (CPU {cpu:.0%})"})
        time.sleep(10)
    out["idle_wait_s"] = round(time.time() - start, 1)
    out["cpu_busy_at_start"] = round(cpu, 3) if cpu is not None else None
    if cpu is not None and cpu >= IDLE_CPU:
        out["flags"].append("busy_at_start")
    out["busy_processes"] = platform.busy_processes()
    out["thermal_at_start"] = monitor.now().thermal
    return out


def make_run_id(label: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{safe}"


def run_benchmark(
    cfg: Config,
    suites=SUITES,
    only_ids: Optional[List[str]] = None,
    quick: bool = False,
    simulate: bool = False,
    on_event: Callable[[Dict[str, Any]], None] = lambda e: None,
    cancel: Optional[threading.Event] = None,
    ae_version: Optional[str] = None,
    c4d_version: Optional[str] = None,
) -> Path:
    platform = get_platform()
    run_id = make_run_id(cfg.label)
    on_event({"type": "status", "message": "Detecting hardware"})
    machine = platform.detect_machine()
    apps = detect_apps(platform, cfg)
    apps["ae_wanted"], apps["c4d_wanted"] = ae_version, c4d_version
    monitor = Monitor(platform).start()
    logs = logs_dir(run_id)
    ctx = RunContext(
        platform=platform, monitor=monitor, config=cfg, run_id=run_id,
        work=work_dir(), logs=logs, quick=quick, apps=apps, on_event=on_event,
        cancel=cancel or threading.Event(), cooldown_s=0 if simulate else None,
    )
    started = datetime.now(timezone.utc)
    tests = build_tests(suites, only_ids, simulate)
    total_iters = sum(t.spec.n_iterations(quick) + (1 if t.spec.warmup else 0) for t in tests) or 1
    done_iters = 0
    iter_started = [time.time()]

    def event(e: Dict[str, Any]) -> None:
        nonlocal done_iters
        if e.get("type") == "iteration":
            if done_iters:
                elapsed = time.time() - iter_started[0]
                e["eta_s"] = round(elapsed / done_iters * (total_iters - done_iters))
            done_iters += 1
            e["progress"] = round(done_iters / total_iters, 3)
        on_event(e)

    ctx.on_event = event
    results: List[Dict[str, Any]] = []
    with platform.keep_awake():
        try:
            pre = {"flags": ["simulated"]} if simulate else preflight(platform, monitor, cfg, quick, on_event)
            iter_started[0] = time.time()
            for t in tests:
                if ctx.cancel.is_set():
                    break
                results.append(run_test(t, ctx))
        finally:
            monitor.stop()

    result = {
        "schema": RESULT_SCHEMA,
        "suite_version": SUITE_VERSION,
        "run_id": run_id,
        "simulated": simulate,
        "label": cfg.label,
        "role": cfg.role,
        "mode": "quick" if quick else "full",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "machine": machine.to_dict(),
        "software": software_summary(apps),
        "builds": {
            "after_effects": _brief_manifest(apps.get("ae_manifest")),
            "cinema4d": _brief_manifest(apps.get("c4d_manifest")),
        },
        "preflight": pre,
        "tests": results,
        "platform": {"python": pyplatform.python_version(), "system": pyplatform.platform()},
        "logs_dir": str(logs),
    }
    path = results_dir() / f"{run_id}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    on_event({"type": "done", "path": str(path), "run_id": run_id})
    return path


def _brief_manifest(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What was actually built, so differing workloads across versions are visible."""
    if not m:
        return None
    keep = ("build_version", "fingerprint", "ae_version", "ae_build", "c4d_version", "bits_per_channel",
            "comps", "render_queue", "missing", "counts", "expression_errors", "octane_available")
    out = {k: m[k] for k in keep if k in m}
    if "scenes" in m:
        out["scenes"] = {k: {"bytes": v.get("bytes"), "frames": v.get("frames")} for k, v in m["scenes"].items()}
    out["workload_complete"] = not m.get("missing") and not m.get("expression_errors")
    return out
