"""Simulated tests for developing the launcher and dashboard without the apps installed.

Every value here is made up. Results produced this way carry "simulated": true,
are labelled DEMO DATA everywhere, and the uploader refuses to send them.
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, List

from ..protocol import BenchTest, Measurement, RunContext, TestSpec


class SimulatedTest(BenchTest):
    def __init__(self, spec: TestSpec, seed: int):
        super().__init__(spec)
        self.rng = random.Random(seed)
        self.base = self.rng.uniform(20, 120)

    def run_once(self, ctx: RunContext, params: Dict[str, Any], iteration: int) -> Measurement:
        time.sleep(0.05)
        v = self.base * self.rng.gauss(1.0, 0.015)
        if self.spec.metric == "fps":
            v = 300.0 / v
        return Measurement(value=v, detail={"simulated": True})


def wrap(specs: List[TestSpec]) -> List[BenchTest]:
    return [SimulatedTest(s, seed=i + 1) for i, s in enumerate(specs)]
