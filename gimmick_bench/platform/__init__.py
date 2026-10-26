"""Pick the platform implementation for the current OS."""
from __future__ import annotations

import sys

from .base import DiskInfo, GPUInfo, MachineInfo, Platform, Sample

_current = None


def get_platform() -> Platform:
    global _current
    if _current is None:
        if sys.platform == "darwin":
            from .macos import MacPlatform
            _current = MacPlatform()
        elif sys.platform.startswith("win"):
            from .windows import WindowsPlatform
            _current = WindowsPlatform()
        else:
            # Development only: real benchmarks need macOS or Windows with the apps installed.
            from .generic import GenericPlatform
            _current = GenericPlatform()
    return _current


__all__ = ["get_platform", "Platform", "MachineInfo", "GPUInfo", "DiskInfo", "Sample"]
