"""Local launcher: a small web page on 127.0.0.1 that runs the benchmark with one click."""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import SUITE_VERSION
from ..config import load_config, save_config

PAGE = Path(__file__).with_name("index.html")


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.events: List[Dict[str, Any]] = []
        self.result_path: Optional[str] = None
        self.error: Optional[str] = None
        self.upload: Optional[str] = None
        self.cancel = threading.Event()
        self.info: Optional[Dict[str, Any]] = None
        self.info_error: Optional[str] = None

    def add(self, e: Dict[str, Any]) -> None:
        e = dict(e, t=time.time())
        with self.lock:
            self.events.append(e)
            del self.events[:-400]

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            last_iter = next((e for e in reversed(self.events) if e.get("type") == "iteration"), None)
            current = next((e for e in reversed(self.events) if e.get("type") == "test_start"), None)
            status = next((e for e in reversed(self.events) if e.get("type") == "status"), None)
            done = [e for e in self.events if e.get("type") == "test_done"]
            return {
                "running": self.running,
                "current": current,
                "status": status["message"] if status else None,
                "progress": last_iter.get("progress") if last_iter else 0,
                "eta_s": last_iter.get("eta_s") if last_iter else None,
                "iteration": last_iter,
                "finished": done,
                "result_path": self.result_path,
                "error": self.error,
                "upload": self.upload,
            }


STATE = State()


def _detect() -> None:
    try:
        from ..platform import get_platform
        from ..runner import detect_apps, software_summary
        p = get_platform()
        cfg = load_config()
        m = p.detect_machine().to_dict()
        sw = software_summary(detect_apps(p, cfg))
        sw.pop("installed", None)
        STATE.info = {"machine": m, "software": sw}
    except Exception as e:  # shown on the page instead of crashing the launcher
        STATE.info_error = str(e)


def _run(options: Dict[str, Any]) -> None:
    from ..runner import SUITES, run_benchmark
    from ..upload import UploadError, upload
    cfg = load_config()
    STATE.cancel.clear()
    try:
        path = run_benchmark(
            cfg, suites=tuple(options.get("suites") or SUITES), quick=bool(options.get("quick")),
            simulate=bool(options.get("simulate")), on_event=STATE.add, cancel=STATE.cancel)
        STATE.result_path = str(path)
        if options.get("simulate"):
            STATE.upload = "Demo data: not sent to the studio sheet."
        elif cfg.sheet_url:
            try:
                upload(path, cfg)
                STATE.upload = "Sent to the studio sheet."
            except UploadError as e:
                STATE.upload = f"Not sent to the sheet: {e}"
        else:
            STATE.upload = "The studio sheet is not set up on this computer; the result is saved locally."
    except Exception as e:
        STATE.error = str(e)
    finally:
        STATE.running = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html") or self.path.startswith("/?"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/info":
            cfg = load_config()
            self._json({"suite_version": SUITE_VERSION, "info": STATE.info, "error": STATE.info_error,
                        "config": {"label": cfg.label, "role": cfg.role, "sheet": bool(cfg.sheet_url)}})
        elif self.path == "/api/state":
            self._json(STATE.snapshot())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        # Only accept requests from this page, not from other sites the browser has open.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and not origin.endswith("//" + host):
            self._json({"error": "forbidden"}, 403)
            return
        data = self._body()
        if self.path == "/api/run":
            if STATE.running:
                self._json({"error": "a benchmark is already running"}, 409)
                return
            STATE.running = True
            STATE.events, STATE.result_path, STATE.error, STATE.upload = [], None, None, None
            threading.Thread(target=_run, args=(data,), daemon=True).start()
            self._json({"ok": True})
        elif self.path == "/api/cancel":
            STATE.cancel.set()
            self._json({"ok": True})
        elif self.path == "/api/config":
            cfg = load_config()
            if data.get("label") is not None:
                cfg.machine_label = str(data["label"])[:60]
            if data.get("role") in ("2d", "3d", "hybrid"):
                cfg.role = data["role"]
            save_config(cfg)
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


def serve(port: int = 0, open_browser: bool = True) -> None:
    threading.Thread(target=_detect, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Gimmick Bench is open at {url}  (keep this window open; press Ctrl+C to quit)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        STATE.cancel.set()
