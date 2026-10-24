"""
evaluate.py  -  NOT part of the Brain's 3 files.
Grades VeriFlow against two baselines on the simulator's answer key (data/labels.csv):

  * Threshold  : "alert if any reading in the last 2 h breaks a fixed limit"
  * IsolationForest : generic anomaly detector on the raw readings

Unit of evaluation = one verdict per site (8 sites).  Run `python simulator.py` and
`python pipeline.py` first (or just `python evaluate.py`, which runs them when needed).
Writes data/processed/evaluation.csv for the dashboard.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, precision_score, recall_score

from bridge import DATA_DIR, OUT_DIR, ensure_data
from main.classify import FAULT, INCIDENT, LABELS, NORMAL

SENSORS = ["ph", "turbidity", "tds", "chlorine"]
LAST_2H = 24                      # readings (5 min each)

# Fixed operating limits for the dumb baseline (min, max).  Placeholders: tune freely.
LIMITS = {"ph": (6.5, 8.5), "turbidity": (0.0, 1.0), "tds": (0.0, 500.0), "chlorine": (0.3, 0.8)}


def threshold_baseline(readings: pd.DataFrame) -> dict:
    """INCIDENT if any of the last 24 readings is outside its fixed limits, else NORMAL."""
    verdict = {}
    for site_id, g in readings.groupby("site_id"):
        recent = g.sort_values("timestamp").tail(LAST_2H)
        breach = any(((recent[c] < lo) | (recent[c] > hi)).any() for c, (lo, hi) in LIMITS.items())
        verdict[site_id] = INCIDENT if breach else NORMAL
    return verdict


def isolation_forest_baseline(readings: pd.DataFrame, min_hits: int = 3) -> dict:
    """INCIDENT if >= min_hits of the last 24 readings are isolation-forest outliers."""
    x = readings[SENSORS].fillna(readings[SENSORS].median())
    model = IsolationForest(contamination=0.02, random_state=42).fit(x)
    out = readings.assign(hit=model.predict(x) == -1)
    verdict = {}
    for site_id, g in out.groupby("site_id"):
        hits = int(g.sort_values("timestamp").tail(LAST_2H)["hit"].sum())
        verdict[site_id] = INCIDENT if hits >= min_hits else NORMAL
    return verdict


def evaluate(verbose: bool = True) -> pd.DataFrame:
    ensure_data()
    readings = pd.read_csv(DATA_DIR / "readings.csv", parse_dates=["timestamp"])
    truth = pd.read_csv(DATA_DIR / "labels.csv").set_index("site_id")["true_class"]
    decisions = pd.read_csv(OUT_DIR / "site_decisions.csv").set_index("site_id")["decision"]

    sites = truth.index.tolist()
    preds = {
        "VeriFlow": decisions.reindex(sites).tolist(),
        "Threshold": [threshold_baseline(readings)[s] for s in sites],
        "IsolationForest": [isolation_forest_baseline(readings)[s] for s in sites],
    }
    y_true = truth.tolist()

    rows = []
    for name, y_pred in preds.items():
        p = precision_score(y_true, y_pred, labels=[INCIDENT], average="macro", zero_division=0)
        r = recall_score(y_true, y_pred, labels=[INCIDENT], average="macro", zero_division=0)
        false_alarms = sum(1 for t, q in zip(y_true, y_pred) if q == INCIDENT and t != INCIDENT)
        missed = sum(1 for t, q in zip(y_true, y_pred) if t == INCIDENT and q != INCIDENT)
        exact = float(np.mean([t == q for t, q in zip(y_true, y_pred)]))
        rows.append({"method": name, "incident_precision": round(p, 2), "incident_recall": round(r, 2),
                     "false_alarms": false_alarms, "missed_incidents": missed,
                     "exact_class_accuracy": round(exact, 2)})
        if verbose:
            print(f"{name}: precision={p:.2f}, recall={r:.2f}, false alarms={false_alarms}, "
                  f"missed incidents={missed}, exact-class accuracy={exact:.2f}")
            print(confusion_matrix(y_true, y_pred, labels=LABELS), "  rows=true, cols=pred, order", LABELS, "\n")

    if verbose:
        detail = pd.DataFrame({"true": y_true, **preds}, index=pd.Index(sites, name="site_id"))
        print(detail.to_string())
    result = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / "evaluation.csv", index=False)
    return result


if __name__ == "__main__":
    evaluate()
