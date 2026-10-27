import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from gimmick_bench.monitors import Monitor
from gimmick_bench.platform.base import Platform, Sample
from gimmick_bench.protocol import (ERROR, INCOMPATIBLE, INVALID, OK, SKIPPED, BenchTest, Measurement,
                                    RunContext, TestSpec, TestUnavailable, run_test)


class QuietPlatform(Platform):
    def __init__(self, thermal="nominal"):
        self.thermal = thermal

    def sample(self):
        return Sample(t=__import__("time").time(), thermal=self.thermal)

    def purge_os_cache(self):
        return False


class Scripted(BenchTest):
    def __init__(self, spec, values):
        super().__init__(spec)
        self.values = list(values)

    def run_once(self, ctx, params, iteration):
        v = self.values.pop(0)
        if isinstance(v, Exception):
            raise v
        if v is None:
            return Measurement(value=None, error="failed")
        return Measurement(value=v)


def ctx(**kw):
    p = QuietPlatform()
    tmp = Path(tempfile.mkdtemp())
    return RunContext(platform=p, monitor=Monitor(p), config=None, run_id="t", work=tmp, logs=tmp,
                      cooldown_s=0, **kw)


class ProtocolTest(unittest.TestCase):
    def test_ok_with_outlier(self):
        t = Scripted(TestSpec("x", "ae", "X"), [70, 60.8, 61.2, 60.9, 61.5, 74.0])
        r = run_test(t, ctx())
        self.assertEqual(r["status"], OK)
        self.assertEqual(r["summary"]["outliers"], [4])
        self.assertEqual(r["warmup"]["value"], 70)
        self.assertEqual(len(r["iterations"]), 5)

    def test_invalid_when_unstable(self):
        t = Scripted(TestSpec("x", "ae", "X"), [10, 10, 14, 18, 22, 26])
        r = run_test(t, ctx())
        self.assertEqual(r["status"], INVALID)
        self.assertIn("spread", r["reason"])

    def test_unavailable_is_flagged_not_zero(self):
        class Missing(Scripted):
            def check(self, c):
                raise TestUnavailable(INCOMPATIBLE, "Octane is not installed")
        r = run_test(Missing(TestSpec("gpu.octane", "gpu", "Octane"), []), ctx())
        self.assertEqual(r["status"], INCOMPATIBLE)
        self.assertEqual(r["reason"], "Octane is not installed")
        self.assertEqual(r["iterations"], [])
        self.assertNotIn("summary", r)

    def test_two_failures_in_a_row_is_error(self):
        t = Scripted(TestSpec("x", "ae", "X", warmup=False), [10.0, None, None, 10.0, 10.0])
        r = run_test(t, ctx())
        self.assertEqual(r["status"], ERROR)

    def test_single_failure_tolerated(self):
        t = Scripted(TestSpec("x", "ae", "X", warmup=False), [10.0, None, 10.1, 10.0, 10.05])
        r = run_test(t, ctx())
        self.assertEqual(r["status"], OK)
        self.assertEqual(r["summary"]["n_total"], 4)

    def test_exception_in_run_once_recorded(self):
        t = Scripted(TestSpec("x", "ae", "X", warmup=False, iterations=3), [ValueError("boom"), 1.0, 1.0])
        r = run_test(t, ctx())
        self.assertIn("ValueError: boom", r["iterations"][0]["error"])

    def test_experimental_skipped(self):
        r = run_test(Scripted(TestSpec("v", "c4d", "V", experimental=True), []), ctx())
        self.assertEqual(r["status"], SKIPPED)

    def test_cancel(self):
        c = ctx()
        c.cancel.set()
        r = run_test(Scripted(TestSpec("x", "ae", "X"), [1, 1, 1, 1, 1, 1]), c)
        self.assertEqual(r["status"], SKIPPED)
        self.assertEqual(r["reason"], "cancelled")

    def test_fps_metric_and_quick(self):
        spec = TestSpec("p", "ae", "P", metric="fps", quick_iterations=3, params={"end": 89}, quick_params={"end": 44})
        c = ctx(quick=True)
        r = run_test(Scripted(spec, [30, 30, 30.2, 29.9]), c)
        self.assertEqual(r["status"], OK)
        self.assertEqual(r["params"]["end"], 44)
        self.assertIn("quick_mode", r["flags"])
        self.assertEqual(c.finished["p"]["median"], 30)

    def test_cold_cache_labelled_without_admin(self):
        spec = TestSpec("c", "c4d", "C", cache="cold", warmup=False, iterations=3)
        r = run_test(Scripted(spec, [5, 5, 5]), ctx())
        self.assertIn("app_cold_only", r["flags"])


class SimulatedRunTest(unittest.TestCase):
    def test_end_to_end_simulated_run(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["GIMMICK_BENCH_HOME"] = home
            try:
                from gimmick_bench.config import Config
                from gimmick_bench.runner import run_benchmark
                from gimmick_bench.upload import UploadError, upload
                events = []
                path = run_benchmark(Config(machine_label="TEST"), quick=True, simulate=True, on_event=events.append)
                data = json.loads(Path(path).read_text())
                self.assertTrue(data["simulated"])
                self.assertEqual(data["schema"], "gimmick-bench/result@1")
                statuses = {t["id"]: t["status"] for t in data["tests"]}
                self.assertTrue(all(s == OK for s in statuses.values()), statuses)
                self.assertNotIn("c4d.viewport", statuses)
                self.assertTrue(any(e.get("type") == "done" for e in events))
                cfg = Config(sheet_url="https://example.invalid", sheet_token="x")
                with self.assertRaises(UploadError):
                    upload(path, cfg)
            finally:
                del os.environ["GIMMICK_BENCH_HOME"]


if __name__ == "__main__":
    unittest.main()
