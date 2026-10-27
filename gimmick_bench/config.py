"""User configuration and working folders.

Config lives in <home>/GimmickBench/config.json so it survives updates of the
benchmark folder. Everything has a safe default; only the Google Sheet upload
needs settings.
"""
from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def home_dir() -> Path:
    override = os.environ.get("GIMMICK_BENCH_HOME")
    return Path(override) if override else Path.home() / "GimmickBench"


@dataclass
class Config:
    # Name shown in the ranking. Defaults to the computer name.
    machine_label: str = ""
    # Main use of this computer: "2d", "3d" or "hybrid". Sets role weights in scoring.
    role: str = "hybrid"
    # Google Apps Script web app URL and shared token (see sheets/README.md).
    sheet_url: str = ""
    sheet_token: str = ""
    # Optional overrides when apps are installed in non-standard places.
    ae_path: str = ""
    c4d_path: str = ""
    # Memory ballast for the multitasking test, in GB. Same on every machine on purpose.
    ballast_gb: float = 8.0
    # Minimum free disk space before a run, in GB.
    min_free_gb: float = 60.0
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.machine_label or socket.gethostname().split(".")[0]


def config_path() -> Path:
    return home_dir() / "config.json"


# Studio-wide settings shipped inside the benchmark folder (not in git: it holds the
# sheet token). Copy the folder with this file to a computer and it uploads with
# no setup there. A computer's own config.json wins for anything it sets.
STUDIO_FILE = REPO_ROOT / "studio.json"


def _read(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in Config.__dataclass_fields__}


def load_config() -> Config:
    data = _read(STUDIO_FILE)
    for k, v in _read(config_path()).items():
        if v not in ("", None) or k not in data:
            data[k] = v
    return Config(**data)


def save_config(cfg: Config) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    return p


def results_dir() -> Path:
    d = home_dir() / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir(run_id: Optional[str] = None) -> Path:
    """Local scratch space for generated projects and render output.

    Always on the local disk so network storage never affects timing.
    """
    d = home_dir() / "work"
    if run_id:
        d = d / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(run_id: str) -> Path:
    d = home_dir() / "logs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d
