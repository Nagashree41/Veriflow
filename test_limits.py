"""Regression tests for limit-aware water quality detection."""
import unittest

import numpy as np
import pandas as pd

from main.detect import (breach_probability, severity_logistic, cusum,
                         time_to_limit, limit_check, analyze_series)
from main.classify import classify_case, INCIDENT, FAULT
from main.score import evidence_score


class LimitTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        self.baseline = rng.normal(7.2, 0.05, 60)
        self.limits = {"ph": {"low": None, "high": 7.5, "sigma": 0.05}}

    def test_breach_probability_at_limit(self):
        self.assertTrue(0.49 <= breach_probability(7.4999, 7.5, 0.05, "high") <= 0.51)

    def test_just_under_limit_alerts(self):
        self.assertTrue(limit_check(np.r_[self.baseline, 7.4999], "ph", self.limits)["limit_alarm"])

    def test_exactly_at_limit_alerts(self):
        self.assertTrue(limit_check(np.r_[self.baseline, 7.5], "ph", self.limits)["limit_alarm"])

    def test_well_below_limit_quiet(self):
        self.assertFalse(limit_check(np.r_[self.baseline, 7.25], "ph", self.limits)["limit_alarm"])

    def test_guard_band_math(self):
        # At 7.40, the stated normal-error formula gives 2.28%; the 5% boundary is ~7.418.
        result = limit_check(np.r_[self.baseline, 7.40], "ph", self.limits)
        self.assertAlmostEqual(result["p_breach"], 0.0228, places=3)
        self.assertFalse(result["limit_alarm"])
        self.assertFalse(limit_check(np.r_[self.baseline, 7.30], "ph", self.limits)["limit_alarm"])

    def test_severity_is_smooth(self):
        scores = [severity_logistic(x, 7.5, 0.05, "high") for x in np.arange(7.3, 7.701, 0.02)]
        self.assertTrue(all(a <= b for a, b in zip(scores, scores[1:])))
        self.assertLess(max(b - a for a, b in zip(scores, scores[1:])), 0.3)

    def test_cusum_catches_drift_before_limit(self):
        rng = np.random.default_rng(2)
        x = np.linspace(7.2, 9.2, 260) + rng.normal(0, 0.01, 260)
        hi, _, alarm, _ = cusum(x, float(np.median(x[:12])), 0.05)
        crossings = np.flatnonzero(hi.to_numpy() > 5.0 * 0.05)
        self.assertTrue(alarm)
        self.assertLess(crossings[0], np.flatnonzero(x >= 8.5)[0])

    def test_cusum_no_false_alarm(self):
        rng = np.random.default_rng(3)
        _, _, alarm, _ = cusum(rng.normal(7.2, 0.05, 300), 7.2, 0.05)
        self.assertFalse(alarm)

    def test_time_to_limit(self):
        values = np.arange(7.0, 7.401, 0.05)
        self.assertAlmostEqual(time_to_limit(values, 7.5, "high"), 2.0, delta=0.1)

    def test_low_side(self):
        limits = {"chlorine": {"low": 0.2, "high": None, "sigma": 0.05}}
        x = np.linspace(1.0, 0.3, 60)
        result = limit_check(x, "chlorine", limits)
        self.assertTrue(result["cusum_alarm"])
        self.assertEqual(result["cusum_direction"], "low")

    def test_nan_handling(self):
        result = limit_check([7.2, np.nan, 7.3, 7.4999], "ph", self.limits)
        self.assertTrue(np.isfinite(result["p_breach"]))
        self.assertTrue(result["limit_alarm"])

    def test_classify_limit_breach_incident(self):
        args = (0.9, 1, 1, 1.0, 0, 0)
        self.assertEqual(classify_case(*args, p_breach=0.6, limit_alarm=True)[0], INCIDENT)
        self.assertEqual(classify_case(0.3, 1, 1, 1.0, 0, 0, p_breach=0.6,
                                       limit_alarm=True)[0], FAULT)

    def test_old_behaviour_unchanged(self):
        self.assertEqual(evidence_score(0.31, 6.0, 1, 0, 0)["score"], 12)
        self.assertEqual(evidence_score(0.96, 4.8, 6, 1, 2)["score"], 75)
        self.assertIn("limit_alarm", analyze_series(pd.Series(self.baseline), "ph", limits=self.limits))


if __name__ == "__main__":
    unittest.main()
