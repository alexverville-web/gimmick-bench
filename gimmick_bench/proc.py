"""Small subprocess helpers shared by platform code and app drivers."""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence


@dataclass
class TimedLine:
    t: float  # perf_counter seconds when the line arrived
    text: str


@dataclass
class ProcResult:
    returncode: Optional[int]
    wall_s: float
    lines: List[TimedLine] = field(default_factory=list)
    timed_out: bool = False

    @property
    def output(self) -> str:
        return "\n".join(l.text for l in self.lines)


def capture(cmd: Sequence[str], timeout: float = 60, env=None) -> str:
    """Run a quick command and return stdout, or an empty string on any failure."""
    try:
        out = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, env=env,
            errors="replace",
        )
        return out.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def run_timed(
    cmd: Sequence[str],
    timeout: float,
    env=None,
    cwd=None,
    on_line: Optional[Callable[[TimedLine], None]] = None,
    log_path=None,
) -> ProcResult:
    """Run a long command, timestamping every output line as it arrives.

    The timestamps let drivers time only the work inside the process (for
    example between aerender's "Starting" and "Finished" lines) and exclude
    application start-up.
    """
    start = time.perf_counter()
    lines: List[TimedLine] = []
    log = open(log_path, "a", encoding="utf-8") if log_path else None
    try:
        proc = subprocess.Popen(
            list(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, cwd=cwd, text=True, bufsize=1, errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except OSError as e:
        if log:
            log.write(f"failed to start: {e}\n")
            log.close()
        return ProcResult(None, 0.0, [TimedLine(0.0, f"failed to start: {e}")])

    def reader():
        assert proc.stdout is not None
        for raw in proc.stdout:
            tl = TimedLine(time.perf_counter(), raw.rstrip("\r\n"))
            lines.append(tl)
            if log:
                log.write(f"[{tl.t - start:10.3f}] {tl.text}\n")
            if on_line:
                on_line(tl)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()
    th.join(timeout=5)
    wall = time.perf_counter() - start
    if log:
        log.close()
    # Re-base timestamps on process start so they are meaningful on their own.
    for l in lines:
        l.t -= start
    return ProcResult(proc.returncode, wall, lines, timed_out)
