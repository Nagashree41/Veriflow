"""Run the complete Persons 1–3 VeriFlow data and decision pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from main.classify import INCIDENT, NORMAL, VERIFY, classify_location
from main.detect import detect_location
from main.score import rank_cases
from validate import validate_csv


SENSORS = ("ph", "turbidity", "tds", "chlorine")
SITE_DECISION_COLUMNS = ["site_id", "decision", "complaints_2h", "reason"]


def _recent_complaints(complaints: pd.DataFrame, end: pd.Timestamp, site_id: object) -> int:
    """Count complaints at a site in the two-hour evidence window."""
    start = end - pd.Timedelta(hours=2)
    return int(((complaints["site_id"] == site_id) & complaints["timestamp"].between(start, end)).sum())


def run_pipeline(readings_path="data/readings.csv", complaints_path="data/complaints.csv",
                 sites_path="data/sites.csv", output_dir="data/processed"):
    """Validate, detect, classify, score, and write dashboard-ready CSVs.

    Ground-truth ``label`` values are carried through source data but are never
    used here.  This makes the generated labels suitable for later evaluation.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reliability_df, _ = validate_csv(readings_path, output)
    readings = pd.read_csv(readings_path, parse_dates=["timestamp"])
    complaints = pd.read_csv(complaints_path, parse_dates=["timestamp"])
    sites = pd.read_csv(sites_path)

    reliability = reliability_df.set_index(["site_id", "sensor"])["reliability"].to_dict()
    sensitivities = sites.set_index("site_id")["sensitivity"].to_dict()
    names = sites.set_index("site_id")["name"].to_dict()
    all_cases, decisions = [], []

    for site_id, group in readings.groupby("site_id", sort=True):
        group = group.sort_values("timestamp", kind="stable")
        end = group["timestamp"].iloc[-1]
        complaints_2h = _recent_complaints(complaints, end, site_id)
        sensor_r = {sensor: reliability[(site_id, sensor)] for sensor in SENSORS}
        detected = detect_location(group, parameters=list(SENSORS), reliabilities=sensor_r)
        cases = classify_location(detected, complaints_2h)
        for case in cases:
            case.update({"site_id": site_id, "location": names.get(site_id, f"Site {site_id}")})
        ranked_for_site = rank_cases(cases, sensitivities)
        all_cases.extend(ranked_for_site)

        if ranked_for_site:
            top = ranked_for_site[0]
            decision, reason = top["label"], "; ".join(top["reasons"])
        else:
            decision, reason = NORMAL, "No corroborated anomaly"
        decisions.append({"site_id": site_id, "decision": decision,
                          "complaints_2h": complaints_2h, "reason": reason})

    ranked = rank_cases(all_cases, sensitivities)
    ranked_df = pd.DataFrame(ranked)
    decisions_df = pd.DataFrame(decisions, columns=SITE_DECISION_COLUMNS)
    ranked_df.to_csv(output / "ranked_alerts.csv", index=False)
    decisions_df.to_csv(output / "site_decisions.csv", index=False)
    return reliability_df, ranked_df, decisions_df


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run VeriFlow's Persons 1–3 pipeline.")
    parser.add_argument("--readings", default="data/readings.csv")
    parser.add_argument("--complaints", default="data/complaints.csv")
    parser.add_argument("--sites", default="data/sites.csv")
    parser.add_argument("--output-dir", default="data/processed")
    args = parser.parse_args(argv)
    _, alerts, decisions = run_pipeline(args.readings, args.complaints, args.sites, args.output_dir)
    print(f"Wrote {len(alerts)} ranked alerts and {len(decisions)} site decisions to {args.output_dir}")
    print(decisions[["site_id", "decision", "complaints_2h"]].to_string(index=False))


if __name__ == "__main__":
    main()
