"""
test_validate.py : unittest suite for validate.py (VeriFlow, Person 2)

All data here is SYNTHETIC and hand-built so every expected result is
explicit. Run with:

    python -m unittest -v test_validate

Expected results are spelled out in each test (weights 0.6/0.6/0.6/0.3,
window 24, stuck run >= 8, unreliable iff R < 0.5).
"""

import copy
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from validate import CONFIG, inspect_sensor, validate_csv

# Exact columns required by the team spec for sensor_reliability.csv.
EXPECTED_RELIABILITY_COLUMNS = [
    "site_id",
    "sensor",
    "missing_count",
    "impossible_count",
    "stuck",
    "spike_count",
    "penalty",
    "reliability",
    "unreliable",
]

SENSOR_COLUMNS = ["ph", "turbidity", "tds", "chlorine"]

# Expected appended columns of validated_readings.csv (score + status each).
EXPECTED_ADDED_COLUMNS = [
    "ph_reliability", "ph_status",
    "turbidity_reliability", "turbidity_status",
    "tds_reliability", "tds_status",
    "chlorine_reliability", "chlorine_status",
]


def varying(n=24, a=7.1, b=7.2):
    """n alternating readings - never stuck, never a spike."""
    return [a, b] * (n // 2)


class InspectSensorTests(unittest.TestCase):
    """Unit tests for inspect_sensor(values, sensor)."""

    # -- 1. normal readings -------------------------------------------------
    def test_normal_readings_are_fully_reliable(self):
        res = inspect_sensor(varying(), "ph")
        self.assertEqual(res["missing_count"], 0)
        self.assertEqual(res["impossible_count"], 0)
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["spike_count"], 0)
        self.assertEqual(res["penalty"], 0.0)
        self.assertEqual(res["reliability"], 1.0)
        self.assertIs(res["unreliable"], False)
        self.assertEqual(res["window_used"], 24)

    # -- 2. missing values --------------------------------------------------
    def test_missing_values_are_counted_and_penalised(self):
        # 18 valid + 6 missing = 24 readings.
        # penalty = 0.6 * 6/24 = 0.15  ->  R = 0.85, still reliable.
        values = varying(18) + [float("nan")] * 6
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["missing_count"], 6)
        self.assertEqual(res["impossible_count"], 0)  # missing != impossible
        self.assertAlmostEqual(res["penalty"], 0.15, places=6)
        self.assertAlmostEqual(res["reliability"], 0.85, places=6)
        self.assertIs(res["unreliable"], False)

    def test_all_missing_marks_sensor_unreliable(self):
        # penalty = 0.6 * 24/24 = 0.6  ->  R = 0.4 < 0.5.
        res = inspect_sensor([float("nan")] * 24, "ph")
        self.assertEqual(res["missing_count"], 24)
        self.assertAlmostEqual(res["penalty"], 0.6, places=6)
        self.assertAlmostEqual(res["reliability"], 0.4, places=6)
        self.assertIs(res["unreliable"], True)

    # -- 3. impossible values ----------------------------------------------
    def test_impossible_ph_20_is_counted(self):
        # 20 alternating valid readings + 4 impossible pH = 20.
        # penalty = 0.6 * 4/24 = 0.1  ->  R = 0.9.
        values = varying() + [20.0] * 4
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["impossible_count"], 4)
        self.assertEqual(res["missing_count"], 0)
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["spike_count"], 0)
        self.assertAlmostEqual(res["penalty"], 0.1, places=6)
        self.assertAlmostEqual(res["reliability"], 0.9, places=6)

    def test_all_impossible_not_double_counted_as_stuck_or_spike(self):
        # 24 x pH 20: impossible only. The invalid values are excluded from
        # stuck and spike detection, so one problem = one category.
        res = inspect_sensor([20.0] * 24, "ph")
        self.assertEqual(res["impossible_count"], 24)
        self.assertEqual(res["missing_count"], 0)
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["spike_count"], 0)
        self.assertAlmostEqual(res["penalty"], 0.6, places=6)
        self.assertAlmostEqual(res["reliability"], 0.4, places=6)
        self.assertIs(res["unreliable"], True)

    # -- 4. stuck sensors ---------------------------------------------------
    def test_stuck_at_least_eight_identical_readings(self):
        # 16 varying + 8 identical = longest run of 8 -> stuck.
        # penalty = 0.6 (flag)  ->  R = 0.4 -> unreliable.
        values = varying(16, 6.9, 7.0) + [7.4] * 8
        res = inspect_sensor(values, "ph")
        self.assertIs(res["stuck"], True)
        self.assertEqual(res["spike_count"], 0)  # 0.4 deviation is no spike
        self.assertAlmostEqual(res["penalty"], 0.6, places=6)
        self.assertAlmostEqual(res["reliability"], 0.4, places=6)
        self.assertIs(res["unreliable"], True)

    def test_seven_identical_readings_are_not_stuck(self):
        # Boundary: run of 7 < 8 -> not stuck, no penalty.
        values = varying(16, 6.9, 7.0) + [7.4] * 7 + [7.0]
        res = inspect_sensor(values, "ph")
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["penalty"], 0.0)
        self.assertEqual(res["reliability"], 1.0)

    def test_missing_value_breaks_a_stuck_run(self):
        # 4 x 5.0, then missing, then 4 x 5.0: runs of 4, not 8.
        # penalty = 0.6 * 1/24 = 0.025  ->  R = 0.975.
        values = [5.0] * 4 + [float("nan")] + [5.0] * 4 + [5.1, 5.2] * 7 + [5.1]
        self.assertEqual(len(values), 24)
        res = inspect_sensor(values, "ph")
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["missing_count"], 1)
        self.assertAlmostEqual(res["penalty"], 0.025, places=6)
        self.assertAlmostEqual(res["reliability"], 0.975, places=6)

    # -- 5. spikes ----------------------------------------------------------
    def test_spike_detected_when_value_returns_to_baseline(self):
        # 23 baseline readings around 7.1/7.2 with one 12.0 in the middle,
        # followed by a normal reading again. pH 12 is still within 0-14, so
        # this is a spike, not an impossible value.
        # penalty = 0.3 * 1/24 = 0.0125  ->  R = 0.9875.
        base = varying()
        values = base[:11] + [12.0] + base[11:23]
        self.assertEqual(len(values), 24)
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["spike_count"], 1)
        self.assertEqual(res["impossible_count"], 0)
        self.assertIs(res["stuck"], False)
        self.assertAlmostEqual(res["penalty"], 0.0125, places=6)
        self.assertAlmostEqual(res["reliability"], 0.9875, places=6)
        self.assertIs(res["unreliable"], False)

    def test_spike_requires_return_to_baseline(self):
        # A sustained shift (two elevated readings at the end, no return)
        # is NOT counted: that may be a real event for Person 3 to judge.
        base = varying()
        values = base[:22] + [12.0, 12.0]
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["spike_count"], 0)
        self.assertEqual(res["penalty"], 0.0)

    def test_spike_at_end_of_window_is_not_yet_confirmed(self):
        # The jump is the LAST reading: there is no "next reading" to confirm
        # the return, so it is not counted as a spike in this window.
        base = varying()
        values = base[:23] + [12.0]
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["spike_count"], 0)

    # -- 6. empty input and insufficient history ----------------------------
    def test_empty_values_are_handled(self):
        res = inspect_sensor([], "ph")
        self.assertEqual(res["window_used"], 0)
        self.assertEqual(res["missing_count"], 0)
        self.assertEqual(res["impossible_count"], 0)
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["spike_count"], 0)
        self.assertEqual(res["penalty"], 0.0)
        self.assertEqual(res["reliability"], 1.0)  # no evidence, not a fault
        self.assertIs(res["unreliable"], False)

    def test_insufficient_history_uses_all_available_readings(self):
        # 5 readings instead of 24: 2 missing.
        # penalty = 0.6 * 2/5 = 0.24  ->  R = 0.76.
        values = [7.1, float("nan"), 7.2, float("nan"), 7.3]
        res = inspect_sensor(values, "ph")
        self.assertEqual(res["window_used"], 5)
        self.assertEqual(res["missing_count"], 2)
        self.assertAlmostEqual(res["penalty"], 0.24, places=6)
        self.assertAlmostEqual(res["reliability"], 0.76, places=6)

    def test_insufficient_history_five_identical_not_stuck(self):
        # Only 5 readings exist, the stuck run needs 8 -> not stuck.
        res = inspect_sensor([6.8] * 5, "ph")
        self.assertEqual(res["window_used"], 5)
        self.assertIs(res["stuck"], False)
        self.assertEqual(res["reliability"], 1.0)

    # -- windowing ----------------------------------------------------------
    def test_only_the_latest_window_is_used(self):
        # Faults in the FIRST 24 of 48 readings must be ignored; the score
        # only looks at the latest 24.
        old = varying() + [20.0] * 4          # impossible pH, but old
        recent = varying()                    # clean latest 24
        res = inspect_sensor(old + recent, "ph")
        self.assertEqual(res["window_used"], 24)
        self.assertEqual(res["impossible_count"], 0)
        self.assertEqual(res["reliability"], 1.0)

    # -- error handling -----------------------------------------------------
    def test_unknown_sensor_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            inspect_sensor([1.0, 2.0], "flow")
        self.assertIn("Known sensors", str(ctx.exception))
        self.assertIn("ph", str(ctx.exception))

    # -- 7/8. score bounds and the exact unreliable rule ---------------------
    def test_reliability_always_within_zero_and_one(self):
        cases = {
            "normal": varying(),
            "all_missing": [float("nan")] * 24,
            "all_impossible": [20.0] * 24,
            "stuck": varying(16, 6.9, 7.0) + [7.4] * 8,
            "spike": varying()[:11] + [12.0] + varying()[11:23],
            # worst case: 8 stuck + 8 missing + 8 impossible -> raw penalty
            # rounds to 1.0 -> R = 0.0 (the lower bound, never below).
            "extreme_mix": [7.4] * 8 + [float("nan")] * 8 + [20.0] * 8,
            "empty": [],
        }
        for name, values in cases.items():
            with self.subTest(case=name):
                res = inspect_sensor(values, "ph")
                self.assertGreaterEqual(res["reliability"], 0.0)
                self.assertLessEqual(res["reliability"], 1.0)
                self.assertGreaterEqual(res["penalty"], 0.0)
                self.assertLessEqual(res["penalty"], 1.0)
        # Explicit check of the lower bound case.
        res = inspect_sensor(cases["extreme_mix"], "ph")
        self.assertEqual(res["reliability"], 0.0)

    def test_unreliable_flag_is_exactly_r_below_half(self):
        cases = [
            varying(),
            varying(18) + [float("nan")] * 6,     # R = 0.85
            [float("nan")] * 24,                  # R = 0.4
            varying() + [20.0] * 4,               # R = 0.9
            varying(16, 6.9, 7.0) + [7.4] * 8,    # R = 0.4 (stuck)
            # R = 0.9875 (spike that returns to baseline)
            varying()[:11] + [12.0] + varying()[11:23],
            [7.4] * 8 + [float("nan")] * 8 + [20.0] * 8,  # R = 0.0
        ]
        for values in cases:
            res = inspect_sensor(values, "ph")
            self.assertEqual(res["unreliable"], res["reliability"] < 0.5)

        # Exact boundary R = 0.5 must be RELIABLE (rule is strictly R < 0.5).
        cfg = copy.deepcopy(CONFIG)
        cfg["weights"]["missing"] = 0.5
        res = inspect_sensor([float("nan")] * 24, "ph", cfg)
        self.assertEqual(res["reliability"], 0.5)
        self.assertIs(res["unreliable"], False)

        # Just below the boundary: R = 0.49 must be UNRELIABLE.
        cfg = copy.deepcopy(CONFIG)
        cfg["weights"]["missing"] = 0.51
        res = inspect_sensor([float("nan")] * 24, "ph", cfg)
        self.assertEqual(res["reliability"], 0.49)
        self.assertIs(res["unreliable"], True)


class ValidateCsvTests(unittest.TestCase):
    """End-to-end tests for validate_csv() on a two-site CSV."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)
        self.outdir = self.tmpdir / "out"

        n = 30
        ts = pd.date_range("2025-03-01 08:00", periods=n, freq="5min")

        # --- siteA: pH faults OUTSIDE the latest-24 window, turbidity gaps
        # inside it. Latest window = rows 6..29 (chronologically last 24).
        ph_a = [7.1 if i % 2 == 0 else 7.2 for i in range(n)]
        ph_a[0] = 20.0   # row 0: impossible, but OUTSIDE the latest-24 window
        ph_a[5] = 20.0   # row 5: impossible, but OUTSIDE the latest-24 window
        turb_a = [3.0 if i % 2 == 0 else 3.5 for i in range(n)]
        for bad in (6, 15, 28):        # all inside the latest-24 window
            turb_a[bad] = float("nan")

        site_a = pd.DataFrame(
            {
                "timestamp": ts,
                "site_id": "siteA",
                "ph": ph_a,
                "turbidity": turb_a,
                "tds": [260 if i % 2 == 0 else 280 for i in range(n)],
                "chlorine": [0.4 if i % 2 == 0 else 0.45 for i in range(n)],
                "label": "normal",
            }
        )

        # --- siteB: pH stuck for the last rows (>= 8 identical readings) ---
        ph_b = [6.9 if i % 2 == 0 else 7.0 for i in range(n)]
        # rows 22..29 become 7.0 (row 21 is already 7.0) -> run of 9 >= 8
        ph_b[22:] = [7.0] * 8
        site_b = pd.DataFrame(
            {
                "timestamp": ts,
                "site_id": "siteB",
                "ph": ph_b,
                "turbidity": [2.0 if i % 2 == 0 else 2.5 for i in range(n)],
                "tds": [300 if i % 2 == 0 else 320 for i in range(n)],
                "chlorine": [0.5 if i % 2 == 0 else 0.55 for i in range(n)],
                "label": "fault_stuck",
            }
        )

        self.input_df = pd.concat([site_a, site_b], ignore_index=True)
        self.input_path = self.tmpdir / "input_readings.csv"
        self.input_df.to_csv(self.input_path, index=False)
        self.input_bytes = self.input_path.read_bytes()

    def _run(self):
        return validate_csv(self.input_path, self.outdir)

    # -- output file contract ------------------------------------------------
    def test_sensor_reliability_csv_columns_are_exact(self):
        self._run()
        on_disk = pd.read_csv(self.outdir / "sensor_reliability.csv")
        self.assertEqual(list(on_disk.columns), EXPECTED_RELIABILITY_COLUMNS)

    def test_grouping_by_site_and_sensor(self):
        rel_df, _ = self._run()
        self.assertEqual(len(rel_df), 8)  # 2 sites x 4 sensors
        pairs = list(zip(rel_df["site_id"], rel_df["sensor"]))
        expected_pairs = {
            (site, sensor)
            for site in ("siteA", "siteB")
            for sensor in SENSOR_COLUMNS
        }
        self.assertEqual(set(pairs), expected_pairs)
        self.assertEqual(len(set(pairs)), 8)  # each pair exactly once

    def test_expected_scores_per_site_and_sensor(self):
        self._run()
        rel = pd.read_csv(self.outdir / "sensor_reliability.csv")

        def row(site, sensor):
            match = rel[(rel["site_id"] == site) & (rel["sensor"] == sensor)]
            self.assertEqual(len(match), 1)
            return match.iloc[0]

        # siteA / ph: the impossible pH rows are OUTSIDE the latest-24 window,
        # so this must score perfectly.
        r = row("siteA", "ph")
        self.assertEqual(r["missing_count"], 0)
        self.assertEqual(r["impossible_count"], 0)
        self.assertIs(bool(r["stuck"]), False)
        self.assertEqual(r["spike_count"], 0)
        self.assertEqual(r["penalty"], 0.0)
        self.assertEqual(r["reliability"], 1.0)
        self.assertIs(bool(r["unreliable"]), False)

        # siteA / turbidity: 3 missing inside the window
        # penalty = 0.6 * 3/24 = 0.075 -> R = 0.925.
        r = row("siteA", "turbidity")
        self.assertEqual(r["missing_count"], 3)
        self.assertAlmostEqual(r["penalty"], 0.075, places=6)
        self.assertAlmostEqual(r["reliability"], 0.925, places=6)
        self.assertIs(bool(r["unreliable"]), False)

        # siteB / ph: stuck (run of 9 identical) -> penalty 0.6 -> R = 0.4.
        r = row("siteB", "ph")
        self.assertIs(bool(r["stuck"]), True)
        self.assertAlmostEqual(r["penalty"], 0.6, places=6)
        self.assertAlmostEqual(r["reliability"], 0.4, places=6)
        self.assertIs(bool(r["unreliable"]), True)

        # siteB / tds: clean.
        r = row("siteB", "tds")
        self.assertEqual(r["reliability"], 1.0)

    def test_window_uses_timestamp_not_file_order(self):
        # Same data but rows in REVERSED file order. The score must still be
        # based on the chronologically latest 24 readings (selected by
        # timestamp), so the results match the normal-order run exactly.
        reversed_df = self.input_df.iloc[::-1].reset_index(drop=True)
        shuffled_path = self.tmpdir / "reversed_readings.csv"
        reversed_df.to_csv(shuffled_path, index=False)

        validate_csv(shuffled_path, self.outdir / "reversed")
        rel = pd.read_csv(self.outdir / "reversed" / "sensor_reliability.csv")

        a_ph = rel[(rel["site_id"] == "siteA") & (rel["sensor"] == "ph")].iloc[0]
        self.assertEqual(a_ph["impossible_count"], 0)  # old faults excluded
        a_turb = rel[(rel["site_id"] == "siteA") & (rel["sensor"] == "turbidity")].iloc[0]
        self.assertEqual(a_turb["missing_count"], 3)   # window faults included

    def test_validated_readings_preserves_original_columns_and_rows(self):
        self._run()
        original = pd.read_csv(self.input_path)
        validated = pd.read_csv(self.outdir / "validated_readings.csv")

        self.assertEqual(
            list(validated.columns),
            list(original.columns) + EXPECTED_ADDED_COLUMNS,
        )
        # All original columns, values and row order unchanged:
        pd.testing.assert_frame_equal(validated[original.columns], original)

    def test_validated_readings_status_follows_reliability_rule(self):
        self._run()
        validated = pd.read_csv(self.outdir / "validated_readings.csv")

        for sensor in SENSOR_COLUMNS:
            rel_col = f"{sensor}_reliability"
            status_col = f"{sensor}_status"
            for _, r in validated.iterrows():
                expected = "investigate" if r[rel_col] < 0.5 else "reliable"
                self.assertEqual(r[status_col], expected)

        # Site-level grouping is visible in the per-row status too.
        self.assertEqual(
            set(validated.loc[validated["site_id"] == "siteA", "ph_status"]),
            {"reliable"},
        )
        self.assertEqual(
            set(validated.loc[validated["site_id"] == "siteB", "ph_status"]),
            {"investigate"},
        )

    def test_unreliable_column_matches_exact_rule_on_disk(self):
        self._run()
        rel = pd.read_csv(self.outdir / "sensor_reliability.csv")
        for _, r in rel.iterrows():
            self.assertEqual(bool(r["unreliable"]), r["reliability"] < 0.5)

    def test_input_file_is_not_modified(self):
        self._run()
        self.assertEqual(self.input_path.read_bytes(), self.input_bytes)

    # -- graceful handling of bad input --------------------------------------
    def test_empty_csv_writes_header_only_outputs(self):
        empty_path = self.tmpdir / "empty.csv"
        header = "timestamp,site_id,ph,turbidity,tds,chlorine,label"
        empty_path.write_text(header + "\n", encoding="utf-8")

        rel_df, val_df = validate_csv(empty_path, self.outdir / "empty")

        self.assertEqual(len(rel_df), 0)
        self.assertEqual(list(rel_df.columns), EXPECTED_RELIABILITY_COLUMNS)
        self.assertEqual(len(val_df), 0)
        self.assertEqual(
            list(val_df.columns),
            ["timestamp", "site_id", "ph", "turbidity", "tds", "chlorine", "label"]
            + EXPECTED_ADDED_COLUMNS,
        )
        first_line = (self.outdir / "empty" / "sensor_reliability.csv").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        self.assertEqual(first_line, ",".join(EXPECTED_RELIABILITY_COLUMNS))

    def test_missing_input_file_raises_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            validate_csv(self.tmpdir / "does_not_exist.csv", self.outdir)

    def test_csv_without_sensor_columns_raises_clear_error(self):
        no_sensors = self.tmpdir / "no_sensors.csv"
        no_sensors.write_text("timestamp,site_id,label\n2025-03-01,siteA,normal\n")
        with self.assertRaises(ValueError) as ctx:
            validate_csv(no_sensors, self.outdir)
        self.assertIn("sensor", str(ctx.exception).lower())

    def test_refuses_to_overwrite_the_input_file(self):
        # If the input happens to be named sensor_reliability.csv, the module
        # must refuse rather than silently destroy it.
        victim = self.tmpdir / "sensor_reliability.csv"
        content = "site_id,sensor\nsiteA,ph\n"
        victim.write_text(content, encoding="utf-8")
        with self.assertRaises(ValueError):
            validate_csv(victim, self.tmpdir)
        self.assertEqual(victim.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
