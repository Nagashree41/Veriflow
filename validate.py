"""
VeriFlow - Evidence Before Alarm
================================
validate.py : sensor reliability validation (Person 2's module)

WHAT THIS MODULE DOES
---------------------
Before the incident detection system makes any decision, this module checks
whether the sensor readings can be trusted. For every site and every sensor it
inspects the latest WINDOW readings and:

  1. counts missing values (empty cells / unparseable text),
  2. counts impossible values (outside configurable physical bounds),
  3. detects stuck sensors (the same VALID value repeated for >= 8 rows),
  4. detects sudden one-reading spikes (jump away from the baseline, then
     return close to it in the very next reading),

then converts those findings into a penalty and a reliability score:

    penalty   = min(1, weighted sum of the four checks)
    R         = 1 - min(1, penalty)          # always within [0, 1]
    unreliable = True when R < 0.5

A sensor with R < 0.5 is flagged FOR SENSOR INVESTIGATION.

WHAT THIS MODULE DOES NOT DO (Person 3 owns this)
-------------------------------------------------
* It does NOT classify incidents, compute confidence scores, or decide whether
  the water is safe or unsafe.
* A low reliability score means "do not trust this sensor right now - check
  the sensor". It is NOT by itself evidence of contamination.
* A reliable sensor with an abnormal reading does NOT automatically prove
  contamination either; that judgement belongs to the incident classifier.
  This module only supplies data-quality results to it.

ALL tunable numbers (weights, bounds, thresholds) live in the single CONFIG
section below so the team can adjust them after testing.

Commands:
    python make_synthetic_data.py
    python validate.py --input synthetic_readings.csv --output-dir .
    python -m unittest -v test_validate
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ===========================================================================
# CONFIGURATION - the ONE place the team edits thresholds and weights
# ===========================================================================

# Per-sensor configurable bounds.
#   min / max        : physical or measurement range; values outside are "impossible"
#   spike_jump       : smallest absolute jump (in the sensor's own unit) that can
#                      count as a spike at all, even when the window is very noisy
#   spike_return     : how close the NEXT reading must be to the baseline for the
#                      jump to count as a "spike that came back"
# NOTE (assumption to confirm with Person 1 / hardware): turbidity 0-1000 NTU,
# TDS 0-5000 and chlorine 0-10 mg/L are placeholder MEASUREMENT ranges, not
# verified specs of the actual probes.
SENSOR_BOUNDS = {
    "ph":        {"min": 0.0,    "max": 14.0,    "spike_jump": 1.0,   "spike_return": 0.5},
    "turbidity": {"min": 0.0,    "max": 1000.0,  "spike_jump": 50.0,  "spike_return": 10.0},
    "tds":       {"min": 0.0,    "max": 5000.0,  "spike_jump": 500.0, "spike_return": 100.0},
    "chlorine":  {"min": 0.0,    "max": 10.0,    "spike_jump": 2.0,   "spike_return": 0.5},
}

# PROVISIONAL penalty weights. A category contribution can never exceed its
# weight, and each category only sees its own share of the window:
#   missing    : weight * (missing_count    / readings_in_window)
#   impossible : weight * (impossible_count / readings_in_window)
#   stuck      : weight * 1.0 if stuck else 0        (it is a boolean flag)
#   spike      : weight * (spike_count      / readings_in_window)
# These four sets of readings are disjoint (see inspect_sensor), so the same
# problem is never charged twice. Team to retune after testing.
WEIGHTS = {"missing": 0.6, "impossible": 0.6, "stuck": 0.6, "spike": 0.3}

WINDOW = 24                    # readings per site used for scoring (latest N)
STUCK_MIN_RUN = 8              # >= 8 consecutive identical valid readings = stuck
STUCK_TOLERANCE = 0.0          # allowed absolute difference between "identical" values
SPIKE_ROBUST_K = 4.0           # jump must also exceed 4 x robust std of the window
RELIABILITY_UNRELIABLE_BELOW = 0.5   # sensor is unreliable when R < 0.5

# Assembled config. inspect_sensor()/validate_csv() accept an optional override
# (useful for experiments and for tests) - e.g. a copy with different weights.
CONFIG = {
    "sensors": SENSOR_BOUNDS,
    "weights": WEIGHTS,
    "window": WINDOW,
    "stuck_min_run": STUCK_MIN_RUN,
    "stuck_tolerance": STUCK_TOLERANCE,
    "spike_robust_k": SPIKE_ROBUST_K,
    "unreliable_below": RELIABILITY_UNRELIABLE_BELOW,
}

# Exact columns of sensor_reliability.csv (agreed with the team).
RELIABILITY_COLUMNS = [
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

__all__ = ["CONFIG", "RELIABILITY_COLUMNS", "inspect_sensor", "validate_csv"]


# ===========================================================================
# Internal helpers
# ===========================================================================

def _detect_stuck(arr, valid, min_run, tolerance):
    """Return True when one valid value repeats for >= min_run consecutive readings.

    Only VALID readings (present and within bounds) can be part of a run; a
    missing or impossible reading breaks the run.

    Limitations:
      - A slowly drifting frozen sensor is not caught (values must repeat).
      - A legitimately constant / heavily quantised sensor can false-positive;
        raise min_run or tolerance for such hardware.
      - Exactly min_run is enough (>=), so the threshold is a hard cliff.
    """
    if arr.size == 0:
        return False
    max_run = 0
    run = 0
    previous = None
    for j in range(arr.size):
        if not valid[j]:
            run = 0          # missing / impossible readings break the run
            previous = None
            continue
        if run > 0 and abs(arr[j] - previous) <= tolerance:
            run += 1
        else:
            run = 1
        previous = arr[j]
        if run > max_run:
            max_run = run
    return max_run >= min_run


def _detect_spikes(arr, valid, bounds, robust_k):
    """Count one-reading spikes inside the window.

    Index i is a spike when ALL of these hold:
      - readings i-1, i and i+1 are all present and within physical bounds,
      - |v[i]   - baseline| >= jump_threshold        (jumped away),
      - |v[i-1] - baseline| <  jump_threshold        (it came from the baseline),
      - |v[i+1] - baseline| <= spike_return          (and came straight back),
    where:
      baseline      = median of the valid readings in the window (robust to the
                      spike itself),
      robust std    = 1.4826 * median absolute deviation,
      jump_threshold = max(bounds["spike_jump"], robust_k * robust std).

    Limitations:
      - The RETURN reading is required, so a spike-like jump as the very last
        reading of the window is not counted yet (it can be confirmed when the
        next reading arrives).
      - A sustained shift to a new level is intentionally NOT a spike - that
        may be a real water event and belongs to Person 3's incident logic.
      - A real contamination pulse can also look like a spike, so a detected
        spike is a property of the signal SHAPE, never proof of a sensor fault.
      - Needs at least 3 valid readings to estimate a baseline at all.
    """
    if int(valid.sum()) < 3:
        return 0

    base_values = arr[valid]
    baseline = float(np.median(base_values))
    robust_std = float(1.4826 * np.median(np.abs(base_values - baseline)))
    jump_threshold = max(float(bounds["spike_jump"]), float(robust_k) * robust_std)
    spike_return = float(bounds["spike_return"])

    count = 0
    for i in range(1, arr.size - 1):
        if not (valid[i - 1] and valid[i] and valid[i + 1]):
            continue
        if (
            abs(arr[i] - baseline) >= jump_threshold
            and abs(arr[i - 1] - baseline) < jump_threshold
            and abs(arr[i + 1] - baseline) <= spike_return
        ):
            count += 1
    return count


# ===========================================================================
# Public API - intended for Person 3 to import
# ===========================================================================

def inspect_sensor(values, sensor, config=None):
    """Score the reliability of ONE sensor's readings.

    Parameters
    ----------
    values : iterable
        Readings for one sensor of one site, in CHRONOLOGICAL order (oldest
        first). Only the latest `config["window"]` entries are used. Entries
        may contain None / NaN / unparseable text - those count as missing.
    sensor : str
        Sensor name; must be a key of CONFIG["sensors"]
        ("ph", "turbidity", "tds", "chlorine").
    config : dict, optional
        Override for CONFIG (same structure), e.g. to try different weights.

    Returns
    -------
    dict with keys:
        sensor, missing_count, impossible_count, stuck (bool), spike_count,
        penalty (0..1), reliability (0..1), unreliable (bool, True iff
        reliability < 0.5), window_used (how many readings were inspected).

    Notes
    -----
    - The window is RETROSPECTIVE: it is the latest N readings of the series
      you pass, not a per-timestep real-time evaluation.
    - No reading is charged to more than one check, so problems are not
      double-counted: missing values are never also "impossible", and stuck /
      spike detection only looks at present, in-bounds readings.
    """
    cfg = CONFIG if config is None else config
    if sensor not in cfg["sensors"]:
        known = ", ".join(cfg["sensors"])
        raise ValueError(f"Unknown sensor {sensor!r}. Known sensors: {known}")

    bounds = cfg["sensors"][sensor]
    lo = float(bounds["min"])
    hi = float(bounds["max"])
    window = int(cfg["window"])

    # Keep only the latest `window` readings (chronological order assumed).
    vals = list(values)
    if window > 0:
        vals = vals[-window:]

    # Anything that is not a number (None, NaN, "ERR", empty text...) -> NaN.
    arr = pd.to_numeric(pd.Series(vals), errors="coerce").to_numpy(dtype=float)
    n = int(arr.size)

    # --- check 1: missing -------------------------------------------------
    nan_mask = np.isnan(arr)
    missing_count = int(nan_mask.sum())

    # --- check 2: impossible (out of physical bounds) ---------------------
    in_bounds = (~nan_mask) & (arr >= lo) & (arr <= hi)
    impossible_count = int(((~nan_mask) & ~in_bounds).sum())

    # --- checks 3 and 4: stuck / spike (valid readings only) --------------
    stuck = _detect_stuck(
        arr, in_bounds, int(cfg["stuck_min_run"]), float(cfg["stuck_tolerance"])
    )
    spike_count = _detect_spikes(arr, in_bounds, bounds, float(cfg["spike_robust_k"]))

    # --- penalty and reliability -----------------------------------------
    weights = cfg["weights"]
    penalty_raw = 0.0
    if n > 0:
        penalty_raw += weights["missing"] * (missing_count / float(n))
        penalty_raw += weights["impossible"] * (impossible_count / float(n))
        penalty_raw += weights["spike"] * (spike_count / float(n))
    if stuck:
        penalty_raw += weights["stuck"]

    penalty = round(min(1.0, penalty_raw), 6)
    reliability = round(1.0 - min(1.0, penalty), 6)   # R = 1 - min(1, penalty)
    unreliable = bool(reliability < float(cfg["unreliable_below"]))

    return {
        "sensor": sensor,
        "missing_count": missing_count,
        "impossible_count": impossible_count,
        "stuck": bool(stuck),
        "spike_count": spike_count,
        "penalty": penalty,
        "reliability": reliability,
        "unreliable": unreliable,
        "window_used": n,
    }


def validate_csv(input_path, output_dir=".", config=None):
    """Validate every site/sensor in a readings CSV and write the two outputs.

    Parameters
    ----------
    input_path : str or Path
        CSV with one row per reading. Recognised columns: sensor columns
        (any subset of ph, turbidity, tds, chlorine - at least one required),
        plus optional timestamp, site_id and label (label is passed through
        untouched; it is ground truth for evaluation, not used for scoring).
    output_dir : str or Path
        Directory for sensor_reliability.csv and validated_readings.csv
        (created if missing). The input file is only ever read, never
        modified - the call refuses to write onto it.
    config : dict, optional
        Override for CONFIG (same structure).

    Returns
    -------
    (reliability_df, validated_df) : the same data that was written to disk.

    Behaviour notes
    ---------------
    - Scores for a site come from that site's latest `window` readings
      (sorted by timestamp when present, otherwise file order). The score is
      site-level and is attached to every row of that site in
      validated_readings.csv; this is a RETROSPECTIVE window evaluation, not a
      fully real-time rolling one.
    - Missing site_id  -> the whole file is treated as one site "site_00".
    - Missing timestamp -> file order is assumed chronological.
    - Empty input (header only) -> both outputs are written with headers and
      zero rows; no exception.
    """
    cfg = CONFIG if config is None else config
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"Input CSV is empty (no header row): {path}") from exc

    sensors = [s for s in cfg["sensors"] if s in df.columns]
    if not sensors:
        expected = ", ".join(cfg["sensors"])
        raise ValueError(
            f"No sensor columns found in {path}. Expected at least one of: {expected}"
        )

    # --- group by site (chronological order for the window) ---------------
    if "site_id" in df.columns:
        grouped = df
        site_key = df["site_id"]
    else:
        grouped = df.copy()
        grouped["site_id"] = "site_00"
        site_key = pd.Series(["site_00"] * len(df), index=df.index)

    site_scores = {}
    for site_id, group in grouped.groupby("site_id", sort=False):
        if "timestamp" in group.columns:
            group = group.sort_values("timestamp", kind="stable")
        site_scores[site_id] = {
            sensor: inspect_sensor(group[sensor].tolist(), sensor, cfg)
            for sensor in sensors
        }

    # --- output 1: sensor_reliability.csv --------------------------------
    rows = []
    for site_id, scored in site_scores.items():
        for sensor in sensors:
            result = scored[sensor]
            rows.append(
                {
                    "site_id": site_id,
                    "sensor": sensor,
                    "missing_count": result["missing_count"],
                    "impossible_count": result["impossible_count"],
                    "stuck": result["stuck"],
                    "spike_count": result["spike_count"],
                    "penalty": result["penalty"],
                    "reliability": result["reliability"],
                    "unreliable": result["unreliable"],
                }
            )
    reliability_df = pd.DataFrame(rows, columns=RELIABILITY_COLUMNS)

    # --- output 2: validated_readings.csv --------------------------------
    # All original columns and row order are preserved; we only APPEND the
    # per-sensor reliability score and status.
    validated_df = df.copy()
    for sensor in sensors:
        validated_df[f"{sensor}_reliability"] = site_key.map(
            lambda site_id, s=sensor: site_scores[site_id][s]["reliability"]
        )
        validated_df[f"{sensor}_status"] = site_key.map(
            lambda site_id, s=sensor: (
                "investigate" if site_scores[site_id][s]["unreliable"] else "reliable"
            )
        )

    # --- write files (input is never touched) -----------------------------
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reliability_path = out_dir / "sensor_reliability.csv"
    validated_path = out_dir / "validated_readings.csv"
    resolved_input = path.resolve()
    for out_path in (reliability_path, validated_path):
        if out_path.resolve() == resolved_input:
            raise ValueError(
                f"Refusing to overwrite the input file with an output file: {path}"
            )
    reliability_df.to_csv(reliability_path, index=False)
    validated_df.to_csv(validated_path, index=False)

    return reliability_df, validated_df


# ===========================================================================
# Command-line entry point
# ===========================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "VeriFlow: compute sensor reliability scores from a readings CSV "
            "and write sensor_reliability.csv + validated_readings.csv."
        )
    )
    parser.add_argument(
        "--input", "-i",
        default="synthetic_readings.csv",
        help="Path to the readings CSV (default: synthetic_readings.csv)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=".",
        help="Directory for the two output files (default: current directory)",
    )
    args = parser.parse_args(argv)

    try:
        reliability_df, validated_df = validate_csv(args.input, args.output_dir)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))  # friendly message, exit status 2

    out_dir = Path(args.output_dir)
    flagged = reliability_df[reliability_df["unreliable"]] if len(reliability_df) else None

    print(f"Input rows validated        : {len(validated_df)}")
    print(f"Wrote {out_dir / 'sensor_reliability.csv'} ({len(reliability_df)} rows)")
    print(f"Wrote {out_dir / 'validated_readings.csv'} ({len(validated_df)} rows)")
    if flagged is None:
        print("Sensors flagged for investigation (R < 0.5): 0 of 0")
    else:
        print(
            f"Sensors flagged for investigation (R < 0.5): "
            f"{len(flagged)} of {len(reliability_df)}"
        )
        for _, row in flagged.iterrows():
            print(
                f"  - {row['site_id']} / {row['sensor']}: "
                f"R = {row['reliability']} (investigate the SENSOR, "
                f"this is not a water-safety verdict)"
            )


if __name__ == "__main__":
    main()
