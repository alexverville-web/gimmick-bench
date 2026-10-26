"""macOS implementation: system_profiler, sysctl, pmset and the Foundation thermal state."""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import json
import os
import plistlib
import platform as pyplatform
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..proc import capture
from . import mac_models
from .base import DiskInfo, GPUInfo, MachineInfo, Platform, Sample

THERMAL_STATES = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}


def parse_size_gb(text) -> Optional[float]:
    """'32 GB' -> 32.0, '1.5 TB' -> 1536.0, '512 MB' -> 0.5."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) / 1024 ** 3
    m = re.match(r"\s*([\d.]+)\s*(TB|GB|MB)", str(text), re.I)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).upper()
    return value * {"TB": 1024, "GB": 1, "MB": 1 / 1024}[unit]


def parse_system_profiler(data: dict) -> Dict:
    """Extract machine facts from `system_profiler -json` output.

    Kept free of side effects so it can be unit-tested with saved output.
    """
    out: Dict = {"gpus": [], "disks": [], "notes": []}
    hw = (data.get("SPHardwareDataType") or [{}])[0]
    out["model_id"] = hw.get("machine_model")
    out["model_name"] = hw.get("machine_name")
    out["cpu"] = hw.get("chip_type") or hw.get("cpu_type") or ""
    out["ram_gb"] = parse_size_gb(hw.get("physical_memory"))
    procs = hw.get("number_processors")
    if isinstance(procs, str) and procs.startswith("proc "):
        # Apple Silicon: "proc 12:8:4" = total:performance:efficiency
        parts = [int(p) for p in procs[5:].split(":") if p.isdigit()]
        if len(parts) == 3:
            out["cpu_cores"], out["p_cores"], out["e_cores"] = parts

    for g in data.get("SPDisplaysDataType") or []:
        name = g.get("sppci_model") or g.get("_name") or "Unknown GPU"
        cores = g.get("sppci_cores")
        vram = g.get("spdisplays_vram") or g.get("_spdisplays_vram")
        vendor = str(g.get("spdisplays_vendor", "")).replace("sppci_vendor_", "") or None
        out["gpus"].append(GPUInfo(
            name=name,
            vram_gb=parse_size_gb(vram),
            cores=int(cores) if str(cores).isdigit() else None,
            vendor=vendor,
        ))

    for v in data.get("SPStorageDataType") or []:
        drive = v.get("physical_drive") or {}
        medium = drive.get("medium_type")
        out["disks"].append(DiskInfo(
            name=v.get("_name", "volume"),
            medium=medium.upper() if medium else None,
            bus=drive.get("protocol"),
            size_gb=round(v["size_in_bytes"] / 1024 ** 3, 1) if v.get("size_in_bytes") else None,
            free_gb=round(v["free_space_in_bytes"] / 1024 ** 3, 1) if v.get("free_space_in_bytes") else None,
            is_boot=v.get("mount_point") == "/",
        ))

    sw = (data.get("SPSoftwareDataType") or [{}])[0]
    out["os_version"] = sw.get("os_version", "")

    mem = data.get("SPMemoryDataType") or []
    slots = []
    for bank in mem:
        slots.extend(bank.get("_items") or [])
    if slots:
        out["ram_slots_total"] = len(slots)
        out["ram_slots_used"] = sum(1 for s in slots if str(s.get("dimm_size", "")).lower() not in ("", "empty"))
    return out


def parse_swapusage(text: str) -> Optional[float]:
    """'total = 2048.00M  used = 1024.50M  free = 1023.50M' -> 1.0 (GB used)."""
    m = re.search(r"used\s*=\s*([\d.]+)([MG])", text)
    if not m:
        return None
    v = float(m.group(1))
    return v / 1024 if m.group(2) == "M" else v


def parse_vm_stat_compressed(text: str) -> Optional[float]:
    page = re.search(r"page size of (\d+) bytes", text)
    comp = re.search(r"Pages occupied by compressor:\s+(\d+)", text)
    if not (page and comp):
        return None
    return int(comp.group(1)) * int(page.group(1)) / 1024 ** 3


def parse_pmset_therm(text: str) -> Optional[int]:
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


class _ThermalReader:
    """Reads NSProcessInfo.thermalState through the Objective-C runtime.

    Available to any process without admin rights on macOS 10.10.3 and later.
    """

    def __init__(self):
        self._fn = None
        try:
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            send_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            send_long = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
            msg = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
            cls = objc.objc_getClass(b"NSProcessInfo")
            info = send_ptr(msg)(cls, objc.sel_registerName(b"processInfo"))
            sel = objc.sel_registerName(b"thermalState")
            fn = send_long(msg)
            self._fn = lambda: fn(info, sel)
            self._fn()
        except Exception:
            self._fn = None

    def read(self) -> Optional[str]:
        if not self._fn:
            return None
        try:
            return THERMAL_STATES.get(int(self._fn()))
        except Exception:
            return None


class MacPlatform(Platform):
    name = "macos"

    def __init__(self):
        self._thermal = _ThermalReader()
        self._is_intel = pyplatform.machine() == "x86_64"

    # --- detection -----------------------------------------------------
    def detect_machine(self) -> MachineInfo:
        raw = capture([
            "system_profiler", "-json", "SPHardwareDataType", "SPDisplaysDataType",
            "SPStorageDataType", "SPSoftwareDataType", "SPMemoryDataType",
        ], timeout=120)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        sp = parse_system_profiler(data)
        info = MachineInfo(
            os="macos",
            os_version=sp.get("os_version") or f"macOS {pyplatform.mac_ver()[0]}",
            computer_name=capture(["scutil", "--get", "ComputerName"]).strip() or socket.gethostname(),
            model_id=sp.get("model_id") or capture(["sysctl", "-n", "hw.model"]).strip() or None,
            manufacturer="Apple",
            arch=pyplatform.machine(),
            cpu=sp.get("cpu") or capture(["sysctl", "-n", "machdep.cpu.brand_string"]).strip(),
            ram_gb=sp.get("ram_gb"),
            gpus=sp["gpus"],
            disks=sp["disks"],
            ram_slots_total=sp.get("ram_slots_total"),
            ram_slots_used=sp.get("ram_slots_used"),
        )
        info.cpu_cores = sp.get("cpu_cores") or _sysctl_int("hw.physicalcpu")
        info.cpu_threads = _sysctl_int("hw.logicalcpu")
        info.p_cores = sp.get("p_cores") or _sysctl_int("hw.perflevel0.physicalcpu")
        info.e_cores = sp.get("e_cores") or _sysctl_int("hw.perflevel1.physicalcpu")
        if info.ram_gb is None:
            mem = _sysctl_int("hw.memsize")
            info.ram_gb = mem / 1024 ** 3 if mem else None

        known = mac_models.lookup(info.model_id)
        cached_name = _cached_marketing_name()
        if known:
            info.model_name, info.model_year, info.ram_upgradeable = known
            info.model_year_source = "model table"
        if cached_name:
            info.model_name = cached_name
            y = mac_models.year_from_marketing_name(cached_name)
            if y:
                info.model_year, info.model_year_source = y, "macOS About This Mac"
        if not info.model_name:
            info.model_name = sp.get("model_name")
        if info.model_year is None:
            info.notes.append("Model year unknown: add this model identifier to mac_models.py")
        info.is_laptop = bool(info.model_name and "MacBook" in info.model_name)
        if info.arch == "arm64":
            info.ram_upgradeable = False
        return info

    # --- monitoring ----------------------------------------------------
    def sample(self) -> Sample:
        s = Sample(t=time.time())
        s.thermal = self._thermal.read()
        if self._is_intel:
            s.cpu_speed_limit = parse_pmset_therm(capture(["pmset", "-g", "therm"], timeout=5))
        try:
            s.load_avg = os.getloadavg()[0]
        except OSError:
            pass
        level = capture(["sysctl", "-n", "kern.memorystatus_level"], timeout=5).strip()
        if level.isdigit():
            s.mem_free_pct = float(level)
        s.swap_used_gb = parse_swapusage(capture(["sysctl", "-n", "vm.swapusage"], timeout=5))
        s.compressed_gb = parse_vm_stat_compressed(capture(["vm_stat"], timeout=5))
        return s

    def on_ac_power(self) -> Optional[bool]:
        out = capture(["pmset", "-g", "batt"], timeout=5)
        if not out:
            return None
        return "AC Power" in out

    def is_admin(self) -> bool:
        if os.geteuid() == 0:
            return True
        return subprocess.call(["sudo", "-n", "true"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0

    @contextlib.contextmanager
    def keep_awake(self):
        p = None
        try:
            p = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
        except OSError:
            pass
        try:
            yield
        finally:
            if p:
                p.terminate()

    def purge_os_cache(self) -> bool:
        cmd = ["purge"] if os.geteuid() == 0 else ["sudo", "-n", "purge"]
        try:
            return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=120) == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def busy_processes(self, limit: int = 5) -> List[Dict]:
        out = capture(["ps", "-Ao", "pcpu=,comm=", "-r"], timeout=10)
        rows = []
        for line in out.splitlines()[: limit + 1]:
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                try:
                    rows.append({"cpu_pct": float(parts[0]), "name": os.path.basename(parts[1])})
                except ValueError:
                    continue
        return [r for r in rows if r["name"] not in ("ps",)][:limit]

    def app_version(self, app_path: Path) -> Optional[str]:
        plist = Path(app_path) / "Contents" / "Info.plist"
        try:
            with open(plist, "rb") as f:
                info = plistlib.load(f)
            return info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
        except (OSError, plistlib.InvalidFileException, ValueError):
            return None

    def default_app_roots(self) -> List[Path]:
        return [Path("/Applications")]


def _sysctl_int(name: str) -> Optional[int]:
    v = capture(["sysctl", "-n", name], timeout=5).strip()
    return int(v) if v.isdigit() else None


def _cached_marketing_name() -> Optional[str]:
    """The name macOS caches after 'About This Mac' is opened, e.g. 'MacBook Pro (14-inch, 2023)'."""
    p = Path.home() / "Library" / "Preferences" / "com.apple.SystemProfiler.plist"
    try:
        with open(p, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    names = data.get("CPU Names") or {}
    for v in names.values():
        if isinstance(v, str) and v:
            return v
    return None
