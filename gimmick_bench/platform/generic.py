"""Fallback platform for development on other systems (Linux). Only useful with --simulate."""
from __future__ import annotations

import contextlib
import os
import platform as pyplatform
import socket
import time

from .base import MachineInfo, Platform, Sample


class GenericPlatform(Platform):
    name = "generic"

    def detect_machine(self) -> MachineInfo:
        info = MachineInfo(
            os=pyplatform.system().lower(), os_version=pyplatform.platform(),
            computer_name=socket.gethostname(), arch=pyplatform.machine(),
            cpu=pyplatform.processor() or pyplatform.machine(), cpu_threads=os.cpu_count(),
        )
        info.notes.append("Unsupported OS for real benchmarks; development use only")
        return info

    def sample(self) -> Sample:
        s = Sample(t=time.time())
        try:
            s.load_avg = os.getloadavg()[0]
        except (OSError, AttributeError):
            pass
        return s

    @contextlib.contextmanager
    def keep_awake(self):
        yield
