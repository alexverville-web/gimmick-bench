"""Command line: python3 -m gimmick_bench <command>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import SUITE_VERSION
from .config import load_config, save_config


def cmd_detect(args) -> int:
    from .platform import get_platform
    from .runner import detect_apps, software_summary
    p = get_platform()
    cfg = load_config()
    out = {"machine": p.detect_machine().to_dict(), "software": software_summary(detect_apps(p, cfg))}
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_list(args) -> int:
    from .runner import all_specs
    for s in all_specs():
        tag = " (experimental, not scored)" if s.experimental else ""
        print(f"{s.id:22} {s.category:10} {s.title}{tag}")
    return 0


def _print_event(e) -> None:
    t = e.get("type")
    if t == "status":
        print(f"  {e['message']}")
    elif t == "test_start":
        print(f"\n> {e['title']} ({e['test']})")
    elif t == "iteration":
        eta = f", about {e['eta_s'] // 60} min left" if e.get("eta_s") else ""
        print(f"    {e['phase']} {e['i']}/{e['n']}  [{e.get('progress', 0):.0%}{eta}]")
    elif t == "test_done":
        reason = f": {e['reason']}" if e.get("reason") else ""
        print(f"  = {e['status']}{reason}")
    elif t == "done":
        print(f"\nResult saved to {e['path']}")
    sys.stdout.flush()


def cmd_run(args) -> int:
    from .runner import SUITES, run_benchmark
    from .upload import UploadError, upload
    cfg = load_config()
    suites = tuple(args.suite) if args.suite else SUITES
    if args.simulate:
        print("SIMULATED RUN: every number is made up (demo data). Nothing will be uploaded.")
    try:
        path = run_benchmark(cfg, suites=suites, only_ids=args.test, quick=args.quick,
                             simulate=args.simulate, on_event=_print_event,
                             ae_version=args.ae_version, c4d_version=args.c4d_version)
    except RuntimeError as e:
        print(f"Could not run the benchmark: {e}", file=sys.stderr)
        return 2
    if not args.simulate and not args.no_upload and cfg.sheet_url:
        try:
            upload(path, cfg)
            print("Sent to the studio sheet.")
        except UploadError as e:
            print(f"Not sent to the sheet: {e}\nThe result is kept locally; send it later with: "
                  f"python3 -m gimmick_bench upload \"{path}\"")
    return 0


def cmd_upload(args) -> int:
    from .upload import UploadError, upload
    try:
        ans = upload(Path(args.file), load_config())
    except UploadError as e:
        print(str(e), file=sys.stderr)
        return 2
    print("Duplicate, already in the sheet." if ans.get("duplicate") else "Sent to the studio sheet.")
    return 0


def cmd_configure(args) -> int:
    cfg = load_config()
    for field in ("machine_label", "role", "sheet_url", "sheet_token", "ae_path", "c4d_path"):
        v = getattr(args, field)
        if v is not None:
            setattr(cfg, field, v)
    if args.ballast_gb is not None:
        cfg.ballast_gb = args.ballast_gb
    if cfg.role not in ("2d", "3d", "hybrid"):
        print("role must be 2d, 3d or hybrid", file=sys.stderr)
        return 2
    print(f"Saved {save_config(cfg)}")
    return 0


def cmd_ui(args) -> int:
    from .ui.server import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gimmick_bench", description=f"Gimmick Bench {SUITE_VERSION}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect", help="show detected hardware and software").set_defaults(fn=cmd_detect)
    sub.add_parser("list", help="list all tests").set_defaults(fn=cmd_list)

    r = sub.add_parser("run", help="run the benchmark")
    r.add_argument("--quick", action="store_true", help="about 45 minutes instead of about 2 hours")
    r.add_argument("--suite", action="append", choices=["ae", "c4d", "gpu", "multitask"],
                   help="only these suites (repeatable)")
    r.add_argument("--test", action="append", help="only this test id (repeatable)")
    r.add_argument("--ae-version", help="After Effects year or version to use, e.g. 2025")
    r.add_argument("--c4d-version", help="Cinema 4D year or version to use, e.g. 2024")
    r.add_argument("--no-upload", action="store_true")
    r.add_argument("--simulate", action="store_true", help="fake numbers for testing the tool (demo data)")
    r.set_defaults(fn=cmd_run)

    u = sub.add_parser("upload", help="send a saved result to the studio sheet")
    u.add_argument("file")
    u.set_defaults(fn=cmd_upload)

    c = sub.add_parser("configure", help="save settings for this computer")
    c.add_argument("--machine-label", dest="machine_label")
    c.add_argument("--role", choices=["2d", "3d", "hybrid"])
    c.add_argument("--sheet-url", dest="sheet_url")
    c.add_argument("--sheet-token", dest="sheet_token")
    c.add_argument("--ae-path", dest="ae_path")
    c.add_argument("--c4d-path", dest="c4d_path")
    c.add_argument("--ballast-gb", dest="ballast_gb", type=float)
    c.set_defaults(fn=cmd_configure)

    g = sub.add_parser("ui", help="open the launcher in the browser")
    g.add_argument("--port", type=int, default=0)
    g.add_argument("--no-browser", action="store_true")
    g.set_defaults(fn=cmd_ui)

    args = ap.parse_args(argv)
    return args.fn(args)
