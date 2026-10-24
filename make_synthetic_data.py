"""
make_synthetic_data.py
----------------------
Creates a small SYNTHETIC test dataset (synthetic_readings.csv) for the
VeriFlow validation module, because the team's real simulator / CSV does not
exist in this project folder yet.

IMPORTANT:
  * Every number in this file is a made-up test fixture. These are NOT real
    sensor measurements and they say NOTHING about real water safety.
  * The file only writes synthetic_readings.csv next to this script; it never
    touches any other file.

Dataset shape (mirrors the agreed simulator format):
  * 8 sites, one row per reading, one reading every 5 minutes, 48 rows/site
    (4 hours), so each site has a full "latest 24 readings" window.
  * Columns: timestamp, site_id, ph, turbidity, tds, chlorine, label
  * `label` is the simulator's ground-truth scenario name for the site.

Scenarios (faults are injected inside the latest-24 window, indices >= 24):
  site_01  normal             clean varying readings
  site_02  normal             clean varying readings
  site_03  fault_missing      4 missing turbidity readings
  site_04  fault_impossible   4 impossible pH readings (pH = 20)
  site_05  fault_stuck        turbidity frozen at 3.0 for 10 consecutive rows
  site_06  fault_spike        one TDS spike that returns to baseline next row
  site_07  fault_mixed        pH stuck (8 identical) + 2 missing chlorine
  site_08  abnormal_but_valid unusual but in-bounds values (must stay reliable)

Run:  python make_synthetic_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SEED = 42                      # fixed seed -> the CSV is reproducible
N_READINGS = 48                # rows per site (48 x 5 min = 4 hours)
OUTPUT_PATH = Path(__file__).resolve().parent / "synthetic_readings.csv"
START_TIME = "2025-03-01 08:00"
WINDOW = 24                    # validate.py scores the latest 24 readings

SCENARIOS = [
    ("site_01", "normal"),
    ("site_02", "normal"),
    ("site_03", "fault_missing"),
    ("site_04", "fault_impossible"),
    ("site_05", "fault_stuck"),
    ("site_06", "fault_spike"),
    ("site_07", "fault_mixed"),
    ("site_08", "abnormal_but_valid"),
]


def build_dataset() -> pd.DataFrame:
    """Build the full synthetic dataframe (8 sites x 48 readings)."""
    rng = np.random.default_rng(SEED)
    n = N_READINGS
    timestamps = pd.date_range(START_TIME, periods=n, freq="5min")
    alt = np.arange(n) % 2  # 0,1,0,1... used to make values vary (never stuck)

    frames = []
    for site_id, label in SCENARIOS:
        # --- normal-looking baseline for every site -----------------------
        ph = np.round(7.2 + rng.normal(0.0, 0.08, n), 3)
        turbidity = np.round(np.clip(2.0 + rng.normal(0.0, 0.4, n), 0, None), 2)
        tds = np.round(300.0 + rng.normal(0.0, 15.0, n), 1)
        chlorine = np.round(np.clip(0.6 + rng.normal(0.0, 0.05, n), 0, None), 3)

        # --- inject the scenario fault (only inside the latest-24 window) --
        if site_id == "site_03":
            # Missing values: 4 turbidity cells become NaN.
            turbidity[[27, 33, 39, 45]] = np.nan

        elif site_id == "site_04":
            # Impossible values: pH 20 is outside the physical range 0-14.
            ph[[30, 36, 42, 46]] = 20.0

        elif site_id == "site_05":
            # Stuck sensor: turbidity frozen at exactly 3.0 for 10 rows.
            turbidity[38:] = 3.0

        elif site_id == "site_06":
            # Sudden spike: TDS jumps ~+900 for ONE row, then the next row
            # returns to the normal baseline (~300).
            tds[40] = round(float(np.median(tds[32:40])) + 900.0, 1)

        elif site_id == "site_07":
            # Mixed: pH frozen at 7.0 for the last 8 rows + 2 missing chlorine.
            ph[40:] = 7.0
            chlorine[[30, 36]] = np.nan

        elif site_id == "site_08":
            # Abnormal but still physically possible readings.
            # validate.py must NOT mark this sensor unreliable.
            ph = np.round(8.6 + rng.normal(0.0, 0.05, n), 3)
            turbidity = np.round(np.clip(120.0 + rng.normal(0.0, 5.0, n), 0, None), 2)
            tds = np.round(450.0 + rng.normal(0.0, 20.0, n), 1)
            chlorine = np.round(np.clip(1.2 + rng.normal(0.0, 0.04, n), 0, None), 3)

        frames.append(
            pd.DataFrame(
                {
                    "timestamp": timestamps,
                    "site_id": site_id,
                    "ph": ph,
                    "turbidity": turbidity,
                    "tds": tds,
                    "chlorine": chlorine,
                    "label": label,
                }
            )
        )

    return pd.concat(frames, ignore_index=True)


def main() -> None:
    df = build_dataset()
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"Wrote {OUTPUT_PATH} ({len(df)} rows, {df['site_id'].nunique()} sites)")
    print("Scenario labels:")
    for site_id, label in df.groupby("site_id", sort=False)["label"].first().items():
        print(f"  {site_id}: {label}")


if __name__ == "__main__":
    main()
