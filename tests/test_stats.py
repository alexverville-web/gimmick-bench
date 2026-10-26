import unittest

from gimmick_bench import stats


class StatsTest(unittest.TestCase):
    def test_median_odd_even(self):
        self.assertEqual(stats.median([3, 1, 2]), 2)
        self.assertEqual(stats.median([4, 1, 2, 3]), 2.5)

    def test_outlier_detected_and_excluded(self):
        values = [60.8, 61.2, 60.9, 61.5, 74.0]
        self.assertEqual(stats.outlier_indices(values), [4])
        s = stats.summarize(values)
        self.assertTrue(s.valid)
        self.assertEqual(s.n_valid, 4)
        self.assertAlmostEqual(s.median, 61.05)

    def test_no_outliers_with_two_values(self):
        self.assertEqual(stats.outlier_indices([1.0, 100.0]), [])

    def test_identical_values_mad_zero(self):
        self.assertEqual(stats.outlier_indices([10.0, 10.0, 10.0, 10.0, 10.5]), [4])
        self.assertEqual(stats.outlier_indices([10.0, 10.0, 10.0, 10.0, 10.0]), [])

    def test_no_outlier_rejection_below_five_runs(self):
        self.assertEqual(stats.outlier_indices([10.0, 10.1, 10.6]), [])
        self.assertTrue(stats.summarize([10.0, 10.1, 10.6]).valid)

    def test_invalid_when_spread_too_high(self):
        s = stats.summarize([10, 13, 16, 19, 22])
        self.assertFalse(s.valid)
        self.assertIn("spread too high", s.reason)

    def test_invalid_when_too_few(self):
        s = stats.summarize([10.0, 10.1], min_valid=3)
        self.assertFalse(s.valid)
        self.assertIn("only 2 valid", s.reason)

    def test_empty(self):
        s = stats.summarize([])
        self.assertFalse(s.valid)
        self.assertIsNone(s.median)

    def test_slowdown(self):
        self.assertAlmostEqual(stats.slowdown_ratio([10, 10, 11, 11]), 0.1)
        self.assertIsNone(stats.slowdown_ratio([10, 11, 12]))


if __name__ == "__main__":
    unittest.main()
