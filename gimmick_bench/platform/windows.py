"""Windows implementation: PowerShell CIM queries, Win32 calls through ctypes, nvidia-smi."""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
import platform as pyplatform
import shutil
import socket
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..proc import capture
from .base import DiskInfo, GPUInfo, MachineInfo, Platform, Sample

# Win32_SystemEnclosure.ChassisTypes values that mean a portable computer.
LAPTOP_CHASSIS = {8, 9, 10, 11, 12, 14, 18, 21, 30, 31, 32}

DETECT_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cs = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
$bios = Get-CimInstance Win32_BIOS
$enc = Get-CimInstance Win32_SystemEnclosure
$cpu = @(Get-CimInstance Win32_Processor)
$gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion, AdapterCompatibility, PNPDeviceID)
$vram = @(Get-ItemProperty 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' |
          Select-Object DriverDesc, 'HardwareInformation.qwMemorySize')
$dimm = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity, Speed)
$arr = Get-CimInstance Win32_PhysicalMemoryArray
$pd = @(Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, Size)
$ld = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID, Size, FreeSpace)
[pscustomobject]@{
  cs = $cs | Select-Object Name, Manufacturer, Model, TotalPhysicalMemory, PCSystemType
  os = $os | Select-Object Caption, Version, BuildNumber, SystemDrive
  bios = $bios | Select-Object ReleaseDate, SMBIOSBIOSVersion
  chassis = @($enc.ChassisTypes)
  cpu = $cpu | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
  gpu = $gpu
  vram = $vram
  dimm = $dimm
  dimm_slots = $arr.MemoryDevices
  pd = $pd
  ld = $ld
} | ConvertTo-Json -Depth 5 -Compress
"""

MEDIA_TYPES = {"3": "HDD", "4": "SSD", "HDD": "HDD", "SSD": "SSD"}
BUS_TYPES = {"17": "NVMe", "11": "SATA", "7": "USB", "8": "RAID", "NVMe": "NVMe", "SATA": "SATA"}


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def parse_cim(data: dict) -> Dict:
    """Turn the PowerShell detection JSON into machine facts (side-effect free)."""
    out: Dict = {"gpus": [], "disks": [], "notes": []}
    cs = data.get("cs") or {}
    os_ = data.get("os") or {}
    out["computer_name"] = cs.get("Name")
    out["manufacturer"] = cs.get("Manufacturer")
    out["model_id"] = cs.get("Model")
    out["model_name"] = " ".join(x for x in [cs.get("Manufacturer"), cs.get("Model")] if x) or None
    if cs.get("TotalPhysicalMemory"):
        out["ram_gb"] = round(int(cs["TotalPhysicalMemory"]) / 1024 ** 3, 1)
    out["os_version"] = f"{os_.get('Caption', 'Windows')} ({os_.get('Version', '')})".strip()

    cpus = _as_list(data.get("cpu"))
    if cpus:
        out["cpu"] = (cpus[0].get("Name") or "").strip()
        out["cpu_cores"] = sum(int(c.get("NumberOfCores") or 0) for c in cpus) or None
        out["cpu_threads"] = sum(int(c.get("NumberOfLogicalProcessors") or 0) for c in cpus) or None

    # The registry value is 64-bit and accurate; AdapterRAM caps at 4 GB.
    reg_vram = {}
    for r in _as_list(data.get("vram")):
        size = r.get("HardwareInformation.qwMemorySize")
        if r.get("DriverDesc") and size:
            reg_vram[r["DriverDesc"]] = int(size) / 1024 ** 3
    for g in _as_list(data.get("gpu")):
        name = (g.get("Name") or "Unknown GPU").strip()
        if "Microsoft Basic" in name or "Remote Display" in name:
            continue
        vram = reg_vram.get(name)
        if vram is None and g.get("AdapterRAM"):
            vram = int(g["AdapterRAM"]) / 1024 ** 3
        out["gpus"].append(GPUInfo(
            name=name,
            vram_gb=round(vram, 1) if vram else None,
            vendor=g.get("AdapterCompatibility"),
            driver=g.get("DriverVersion"),
        ))

    free_by_drive = {}
    for l in _as_list(data.get("ld")):
        if l.get("DeviceID") and l.get("FreeSpace") is not None:
            free_by_drive[l["DeviceID"]] = round(int(l["FreeSpace"]) / 1024 ** 3, 1)
    system_drive = (os_.get("SystemDrive") or "C:").upper()
    for i, d in enumerate(_as_list(data.get("pd"))):
        out["disks"].append(DiskInfo(
            name=d.get("FriendlyName") or f"disk {i}",
            medium=MEDIA_TYPES.get(str(d.get("MediaType"))),
            bus=BUS_TYPES.get(str(d.get("BusType")), str(d.get("BusType")) if d.get("BusType") else None),
            size_gb=round(int(d["Size"]) / 1024 ** 3, 1) if d.get("Size") else None,
        ))
    if out["disks"]:
        # Physical disks do not map to drive letters without more queries; report
        # system drive free space on the first disk, which is where we work.
        out["disks"][0].free_gb = free_by_drive.get(system_drive)
        out["disks"][0].is_boot = True

    dimms = _as_list(data.get("dimm"))
    if dimms:
        out["ram_slots_used"] = len(dimms)
    if data.get("dimm_slots"):
        out["ram_slots_total"] = int(data["dimm_slots"])

    chassis = {int(c) for c in _as_list(data.get("chassis")) if str(c).isdigit()}
    pc_type = (data.get("cs") or {}).get("PCSystemType")
    out["is_laptop"] = bool(chassis & LAPTOP_CHASSIS) or pc_type == 2

    bios_date = (data.get("bios") or {}).get("ReleaseDate")
    year = _bios_year(bios_date)
    if year:
        out["model_year"] = year
        out["model_year_source"] = "BIOS date (estimate)"
    return out


def _bios_year(v) -> Optional[int]:
    if not v:
        return None
    s = str(v)
    # CIM dates arrive as "/Date(1600000000000)/" or "20200115000000.000000+000"
    if s.startswith("/Date("):
        try:
            ms = int(s[6:].split(")")[0].split("+")[0].split("-")[0])
            return time.gmtime(ms / 1000).tm_year
        except ValueError:
            return None
    if s[:4].isdigit():
        return int(s[:4])
    return None


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]

    @property
    def value(self) -> int:
        return (self.hi << 32) | self.lo


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong),
    ]


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class WindowsPlatform(Platform):
    name = "windows"

    def __init__(self):
        self._k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        self._last_times = None
        self._nvsmi = shutil.which("nvidia-smi")

    def _powershell(self, script: str, timeout: float = 120) -> str:
        return capture(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)

    def detect_machine(self) -> MachineInfo:
        raw = self._powershell(DETECT_PS)
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            data = {}
        p = parse_cim(data)
        info = MachineInfo(
            os="windows",
            os_version=p.get("os_version") or f"Windows {pyplatform.version()}",
            computer_name=p.get("computer_name") or socket.gethostname(),
            model_id=p.get("model_id"),
            model_name=p.get("model_name"),
            manufacturer=p.get("manufacturer"),
            model_year=p.get("model_year"),
            model_year_source=p.get("model_year_source"),
            arch=pyplatform.machine().lower().replace("amd64", "x86_64"),
            cpu=p.get("cpu", ""),
            cpu_cores=p.get("cpu_cores"),
            cpu_threads=p.get("cpu_threads"),
            ram_gb=p.get("ram_gb"),
            ram_slots_total=p.get("ram_slots_total"),
            ram_slots_used=p.get("ram_slots_used"),
            is_laptop=p.get("is_laptop"),
            gpus=p["gpus"],
            disks=p["disks"],
        )
        if info.ram_slots_total and info.ram_slots_used is not None:
            info.ram_upgradeable = (not info.is_laptop) or info.ram_slots_used < info.ram_slots_total
        self._nvidia_vram(info)
        if info.model_year_source:
            info.notes.append("Model year estimated from the BIOS release date")
        return info

    def _nvidia_vram(self, info: MachineInfo) -> None:
        if not self._nvsmi:
            return
        out = capture([self._nvsmi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[1].isdigit():
                for g in info.gpus:
                    if parts[0] in g.name or g.name in parts[0]:
                        g.vram_gb = round(int(parts[1]) / 1024, 1)

    def sample(self) -> Sample:
        s = Sample(t=time.time())
        st = _MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if self._k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            s.mem_free_pct = 100.0 * st.ullAvailPhys / st.ullTotalPhys
            # Commit beyond physical RAM is what spills to the page file.
            committed = st.ullTotalPageFile - st.ullAvailPageFile
            s.swap_used_gb = max(0.0, (committed - st.ullTotalPhys) / 1024 ** 3)
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        if self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            now = (idle.value, kern.value + user.value)
            if self._last_times:
                d_idle = now[0] - self._last_times[0]
                d_total = now[1] - self._last_times[1]
                if d_total > 0:
                    s.cpu_busy = max(0.0, min(1.0, 1.0 - d_idle / d_total))
            self._last_times = now
        if self._nvsmi:
            out = capture([self._nvsmi, "--query-gpu=temperature.gpu,clocks_throttle_reasons.active",
                           "--format=csv,noheader,nounits"], timeout=5)
            first = out.splitlines()[0].split(",") if out.strip() else []
            if len(first) == 2:
                try:
                    s.gpu_temp_c = float(first[0])
                    # Only count hardware slowdown (0x8) and thermal (0x20, 0x40) reasons;
                    # a power cap under full load is normal.
                    s.gpu_throttle = int(first[1].strip(), 16) & 0x68 != 0
                except ValueError:
                    pass
        return s

    def on_ac_power(self) -> Optional[bool]:
        st = _SYSTEM_POWER_STATUS()
        if not self._k32.GetSystemPowerStatus(ctypes.byref(st)):
            return None
        if st.ACLineStatus == 255:
            return None
        return st.ACLineStatus == 1

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False

    @contextlib.contextmanager
    def keep_awake(self):
        self._k32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        try:
            yield
        finally:
            self._k32.SetThreadExecutionState(ES_CONTINUOUS)

    def purge_os_cache(self) -> bool:
        # Windows has no supported equivalent of macOS `purge`; cold-cache runs
        # are labelled "app-cold only" on Windows.
        return False

    def busy_processes(self, limit: int = 5) -> List[Dict]:
        script = (
            "Get-Counter '\\Process(*)\\% Processor Time' -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty CounterSamples | "
            "Where-Object { $_.InstanceName -notin @('_total','idle') } | "
            f"Sort-Object CookedValue -Descending | Select-Object -First {limit} InstanceName, CookedValue | "
            "ConvertTo-Json -Compress"
        )
        out = self._powershell(script, timeout=30)
        try:
            rows = json.loads(out) if out.strip() else []
        except ValueError:
            return []
        n = os.cpu_count() or 1
        return [{"name": r["InstanceName"], "cpu_pct": round(r["CookedValue"] / n, 1)} for r in _as_list(rows)]

    def app_version(self, app_path: Path) -> Optional[str]:
        safe = str(app_path).replace("'", "''")
        out = self._powershell(f"(Get-Item '{safe}').VersionInfo.ProductVersion", timeout=30).strip()
        return out or None

    def default_app_roots(self) -> List[Path]:
        roots = []
        for var in ("ProgramFiles", "ProgramW6432"):
            v = os.environ.get(var)
            if v and Path(v) not in roots:
                roots.append(Path(v))
        return roots or [Path("C:/Program Files")]
