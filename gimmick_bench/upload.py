"""Send a result file to the studio Google Sheet through its Apps Script web app."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from .config import Config


class UploadError(RuntimeError):
    pass


def build_payload(result: Dict[str, Any], token: str) -> bytes:
    if result.get("simulated"):
        raise UploadError("This is a simulated (demo) run. Demo data is never sent to the studio sheet.")
    return json.dumps({"token": token, "result": result}).encode("utf-8")


def upload(path: Path, cfg: Config, timeout: float = 120) -> Dict[str, Any]:
    if not cfg.sheet_url or not cfg.sheet_token:
        raise UploadError("The Google Sheet is not set up on this computer yet (see sheets/README.md).")
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    body = build_payload(result, cfg.sheet_token)
    req = urllib.request.Request(cfg.sheet_url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        # Apps Script answers with a redirect to the response; urllib follows it as a GET.
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise UploadError(f"Could not reach the Google Sheet: {e}") from e
    try:
        answer = json.loads(text)
    except ValueError:
        raise UploadError("The Google Sheet answered with something unexpected. "
                          "Check that the web app is deployed with access 'Anyone'.")
    if not answer.get("ok"):
        raise UploadError(f"The Google Sheet refused the result: {answer.get('error')}")
    return answer
