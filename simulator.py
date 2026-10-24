"""Generate reproducible fake water-quality data for the VeriFlow hackathon."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


SITES_COLUMNS = ["site_id", "name", "lat", "lng", "sensitivity"]
READINGS_COLUMNS = ["site_id", "timestamp", "ph", "turbidity", "tds", "chlorine"]
COMPLAINTS_COLUMNS = ["site_id", "timestamp"]
LABELS_COLUMNS = ["site_id", "start", "end", "scenario", "true_class"]


def _normalise_end_time(end_time: object | None) -> datetime:
    """Return a second-free timestamp floored to a five-minute boundary."""
    if end_time is None:
        value = datetime.now()
    elif isinstance(end_time, datetime):
        value = end_time
    else:
        value = datetime.fromisoformat(str(end_time))
    return value.replace(second=0, microsecond=0, minute=(value.minute // 5) * 5)


def _timestamp_strings(times: list[datetime]) -> list[str]:
    return [moment.strftime("%Y-%m-%d %H:%M:%S") for moment in times]


def generate(seed=42, end_time=None):
    """Return (sites, readings, complaints, labels) for a 24-hour VeriFlow demo."""
    rng = np.random.default_rng(seed)
    end = _normalise_end_time(end_time)
    times = [end - timedelta(minutes=5 * offset) for offset in range(287, -1, -1)]
    timestamp_values = _timestamp_strings(times)

    # Fixed, plausible Bengaluru positions; sensitivity represents local impact.
    sites = pd.DataFrame(
        [
            (1, "Site 1", 12.9716, 77.5946, 0.35),
            (2, "Site 2", 12.9352, 77.6245, 0.45),
            (3, "Site 3", 12.9981, 77.5712, 0.90),
            (4, "Site 4", 13.0318, 77.6104, 0.30),
            (5, "Site 5", 12.9467, 77.5561, 0.70),
            (6, "Site 6", 13.0462, 77.6658, 0.50),
            (7, "Site 7", 12.9148, 77.6437, 0.25),
            (8, "Site 8", 13.0147, 77.5234, 0.40),
        ],
        columns=SITES_COLUMNS,
    )

    baselines = {"ph": 7.4, "turbidity": 0.8, "tds": 250.0, "chlorine": 0.6}
    noise = {"ph": 0.05, "turbidity": 0.05, "tds": 5.0, "chlorine": 0.03}
    decimals = {"ph": 2, "turbidity": 2, "tds": 1, "chlorine": 2}
    rows = []
    for site_id in range(1, 9):
        # Offsets are deliberately only about one tenth of ordinary sensor noise.
        offsets = {key: rng.normal(0, std * 0.1) for key, std in noise.items()}
        values = {
            key: baselines[key] + offsets[key] + rng.normal(0, noise[key], len(times))
            for key in baselines
        }
        for key, places in decimals.items():
            values[key] = np.round(values[key], places)
        for index, timestamp in enumerate(timestamp_values):
            rows.append((site_id, timestamp, *(values[key][index] for key in READINGS_COLUMNS[2:])))

    readings = pd.DataFrame(rows, columns=READINGS_COLUMNS)

    # Story injections use positional indices within each site's chronologically sorted data.
    def site_rows(site_id):
        return readings.index[readings["site_id"] == site_id]

    idx2 = site_rows(2)
    readings.loc[idx2[-4], "chlorine"] = round(float(readings.loc[idx2[-4], "chlorine"]) + 0.30, 2)

    idx3 = site_rows(3)
    readings.loc[idx3[-8:], "chlorine"] = np.round(rng.normal(0.20, 0.01, 8), 2)
    readings.loc[idx3[-8:], "turbidity"] = np.round(rng.normal(3.00, 0.08, 8), 2)

    idx4 = site_rows(4)
    readings.loc[idx4[-12:], "tds"] = readings.loc[idx4[-13], "tds"]

    idx6 = site_rows(6)
    readings.loc[idx6[-14:-4], "turbidity"] = np.nan
    readings.loc[idx6[-3:], "ph"] = 15.0

    # Complaint timestamps are sampled from the final two hours (the final 24 readings).
    complaint_rows = []
    for site_id, count in ((3, 2), (5, 3)):
        selected = rng.choice(timestamp_values[-24:], size=count, replace=False)
        complaint_rows.extend((site_id, timestamp) for timestamp in sorted(selected))
    complaints = pd.DataFrame(complaint_rows, columns=COMPLAINTS_COLUMNS).sort_values(
        ["site_id", "timestamp"], ignore_index=True
    )

    labels = pd.DataFrame(
        [
            (1, timestamp_values[0], timestamp_values[-1], "normal", "Normal"),
            (2, timestamp_values[-4], timestamp_values[-4], "spike", "Normal"),
            (3, timestamp_values[-8], timestamp_values[-1], "incident", "Potential Incident"),
            (4, timestamp_values[-12], timestamp_values[-1], "stuck", "Sensor Fault Suspected"),
            (5, complaints.loc[complaints.site_id.eq(5), "timestamp"].min(), complaints.loc[complaints.site_id.eq(5), "timestamp"].max(), "complaints_only", "Needs Verification"),
            (6, timestamp_values[-14], timestamp_values[-1], "missing_or_out_of_range", "Sensor Fault Suspected"),
            (7, timestamp_values[0], timestamp_values[-1], "normal", "Normal"),
            (8, timestamp_values[0], timestamp_values[-1], "normal", "Normal"),
        ],
        columns=LABELS_COLUMNS,
    )
    return sites, readings, complaints, labels


def save(sites, readings, complaints, labels, folder="data"):
    """Write VeriFlow tables to *folder* and represent missing values as blank CSV cells."""
    output = Path(folder)
    output.mkdir(parents=True, exist_ok=True)
    sites.to_csv(output / "sites.csv", index=False)
    readings.to_csv(output / "readings.csv", index=False, na_rep="")
    complaints.to_csv(output / "complaints.csv", index=False)
    labels.to_csv(output / "labels.csv", index=False)


def _self_check(sites, readings, complaints, labels):
    """Assert every promised story condition, then print a concise verification report."""
    assert list(sites.columns) == SITES_COLUMNS
    assert list(readings.columns) == READINGS_COLUMNS
    assert list(complaints.columns) == COMPLAINTS_COLUMNS
    assert list(labels.columns) == LABELS_COLUMNS
    assert len(sites) == 8 and len(readings) == 2304, "Expected 8 sites and 2,304 readings."
    per_site = readings.groupby("site_id").size()
    assert per_site.index.tolist() == list(range(1, 9)) and (per_site == 288).all(), "Each site must have 288 readings."

    by_site = {site: readings.loc[readings.site_id.eq(site)].reset_index(drop=True) for site in range(1, 9)}
    assert 0.85 <= by_site[2].loc[284, "chlorine"] <= 0.98, "Site 2 spike is not approximately +0.30."
    assert 0.45 <= by_site[2].iloc[-1].chlorine <= 0.75, "Site 2 latest chlorine must be normal."
    assert (by_site[3].tail(8).chlorine.between(0.16, 0.24)).all(), "Site 3 chlorine story failed."
    assert (by_site[3].tail(8).turbidity.between(2.7, 3.3)).all(), "Site 3 turbidity story failed."
    assert by_site[4].tail(12).tds.nunique() == 1, "Site 4 TDS values are not stuck."
    assert by_site[4].tail(12).tds.iloc[0] == by_site[4].iloc[-13].tds, "Site 4 stuck value is wrong."
    assert by_site[6].turbidity.isna().sum() == 10, "Site 6 must have exactly 10 missing turbidity values."
    assert by_site[6].iloc[-14:-4].turbidity.isna().all(), "Site 6 missing interval is wrong."
    assert (by_site[6].tail(3).ph == 15.0).all(), "Site 6 final pH values must be 15.0."
    counts = complaints.groupby("site_id").size().reindex(range(1, 9), fill_value=0)
    assert counts.to_dict() == {1: 0, 2: 0, 3: 2, 4: 0, 5: 3, 6: 0, 7: 0, 8: 0}, "Complaint counts are wrong."
    last_two_hours = readings.timestamp.drop_duplicates().iloc[-24:].tolist()
    assert complaints.timestamp.isin(last_two_hours).all(), "Every complaint must be in the final two hours."
    assert set(labels.scenario) == {"spike", "incident", "stuck", "complaints_only", "missing_or_out_of_range", "normal"}

    print("Rows per site:")
    print(per_site.to_string())
    print("\nSite stories and labels:")
    print(labels[["site_id", "scenario", "true_class"]].to_string(index=False))
    print("\nSite 3: last 8 readings:")
    print(by_site[3].tail(8).to_string(index=False))
    print("\nSite 4: last 12 TDS values:")
    print(by_site[4].tail(12)[["timestamp", "tds"]].to_string(index=False))
    print("\nSite 6 NaN turbidity values:", int(by_site[6].turbidity.isna().sum()))
    print("Site 6 last 3 pH values:", by_site[6].tail(3).ph.tolist())
    print("\nComplaint counts per site:")
    print(counts.to_string())
    print("ALL CHECKS PASSED")


def main():
    parser = argparse.ArgumentParser(description="Create VeriFlow fake water-quality CSV data.")
    parser.add_argument("--seed", type=int, default=42, help="NumPy random seed (default: 42).")
    parser.add_argument("--fixed-end", help='Fixed end time, e.g. "2025-10-31 12:00".')
    args = parser.parse_args()
    sites, readings, complaints, labels = generate(seed=args.seed, end_time=args.fixed_end)
    save(sites, readings, complaints, labels)
    _self_check(sites, readings, complaints, labels)


if __name__ == "__main__":
    main()
