"""Platform interface. Every OS-specific call the benchmark makes goes through here."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class GPUInfo:
    name: str
    vram_gb: Optional[float] = None  # None on Apple Silicon (unified memory)
    cores: Optional[int] = None
    vendor: Optional[str] = None
    driver: Optional[str] = None


@dataclass
class DiskInfo:
    name: str
    medium: Optional[str] = None  # "SSD", "HDD" or None if unknown
    bus: Optional[str] = None  # "NVMe", "SATA", "Apple Fabric", ...
    size_gb: Optional[float] = None
    free_gb: Optional[float] = None
    is_boot: bool = False


@dataclass
class MachineInfo:
    os: str  # "macos" | "windows"
    os_version: str
    computer_name: str
    model_id: Optional[str] = None  # e.g. "Mac14,13" or "Precision 7865"
    model_name: Optional[str] = None  # e.g. "Mac Studio (2023)"
    manufacturer: Optional[str] = None
    model_year: Optional[int] = None
    model_year_source: Optional[str] = None  # "table", "system_profiler", "bios_date", ...
    arch: str = ""  # "arm64" | "x86_64"
    cpu: str = ""
    cpu_cores: Optional[int] = None
    cpu_threads: Optional[int] = None
    p_cores: Optional[int] = None
    e_cores: Optional[int] = None
    ram_gb: Optional[float] = None
    ram_slots_total: Optional[int] = None
    ram_slots_used: Optional[int] = None
    ram_upgradeable: Optional[bool] = None
    is_laptop: Optional[bool] = None
    gpus: List[GPUInfo] = field(default_factory=list)
    disks: List[DiskInfo] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Sample:
    """One monitoring sample. Fields a platform cannot read stay None."""
    t: float
    thermal: Optional[str] = None  # "nominal" | "fair" | "serious" | "critical"
    cpu_speed_limit: Optional[int] = None  # Intel Macs: percent of max clock allowed
    cpu_busy: Optional[float] = None  # 0..1 whole-system CPU use
    load_avg: Optional[float] = None
    mem_free_pct: Optional[float] = None
    swap_used_gb: Optional[float] = None
    compressed_gb: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    gpu_throttle: Optional[bool] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


class Platform:
    name = "base"

    def detect_machine(self) -> MachineInfo:
        raise NotImplementedError

    def sample(self) -> Sample:
        raise NotImplementedError

    def on_ac_power(self) -> Optional[bool]:
        return None

    def is_admin(self) -> bool:
        return False

    def keep_awake(self):
        """Return a context manager that prevents sleep during the run."""
        raise NotImplementedError

    def purge_os_cache(self) -> bool:
        """Clear the OS file cache if allowed. Returns False when not possible."""
        return False

    def busy_processes(self, limit: int = 5) -> List[Dict]:
        """Top CPU consumers right now, for the background-activity check."""
        return []

    def app_version(self, app_path: Path) -> Optional[str]:
        return None

    def default_app_roots(self) -> List[Path]:
        return []
