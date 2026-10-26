"""Memory ballast for the multitasking test.

Holds a fixed amount of RAM and keeps touching it, standing in for the
Photoshop, Illustrator, browser and chat apps a designer has open. The size is
the same on every machine on purpose: a 16 GB computer should feel it more
than a 64 GB one, because that is the real production problem.

Run as: python -m gimmick_bench.ballast <gigabytes>
"""
from __future__ import annotations

import sys
import time

PAGE = 4096


def main() -> None:
    gb = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    size = int(gb * 1024 ** 3)
    buf = bytearray(size)
    for i in range(0, size, PAGE):
        buf[i] = 1
    print("ready", flush=True)
    n = 0
    while True:
        n = (n + 1) % 255
        for i in range(0, size, PAGE * 4):
            buf[i] = n
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, MemoryError):
        pass
