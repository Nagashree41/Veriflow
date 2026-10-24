"""
evaluate.py  -  NOT part of the Brain's 3 files.
Grades VeriFlow against the threshold-only baseline using scikit-learn.
The three lists below are PLACEHOLDERS: replace them with real output from
your seeded generator (y_true) and from detect/classify/score (y_veriflow).
"""
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, confusion_matrix
from sklearn.ensemble import IsolationForest

from classify import LABELS, NORMAL, FAULT, VERIFY, INCIDENT

# --- Placeholder data (all lists must be the same length, same event order) ---
y_true     = [NORMAL, NORMAL,   FAULT,    FAULT,    VERIFY, INCIDENT, INCIDENT, NORMAL, FAULT,    INCIDENT]
y_veriflow = [NORMAL, NORMAL,   FAULT,    VERIFY,   VERIFY, INCIDENT, INCIDENT, NORMAL, FAULT,    INCIDENT]
y_baseline = [NORMAL, INCIDENT, INCIDENT, INCIDENT, NORMAL, INCIDENT, INCIDENT, NORMAL, INCIDENT, INCIDENT]

for name, y_pred in [("VeriFlow", y_veriflow), ("Threshold", y_baseline)]:
    p = precision_score(y_true, y_pred, labels=[INCIDENT], average="macro", zero_division=0)
    r = recall_score(y_true, y_pred, labels=[INCIDENT], average="macro", zero_division=0)
    print(f"{name}: precision={p:.2f}, recall={r:.2f}")
    print(confusion_matrix(y_true, y_pred, labels=LABELS))
    print()

# --- Optional: Isolation Forest comparison on placeholder sensor data ---
rng = np.random.default_rng(42)
df = pd.DataFrame({
    "ph": rng.normal(7.2, 0.2, 200), "turbidity": rng.normal(1.0, 0.3, 200),
    "tds": rng.normal(300, 20, 200), "chlorine": rng.normal(1.5, 0.2, 200),
})
features = ["ph", "turbidity", "tds", "chlorine"]
model = IsolationForest(contamination=0.05, random_state=42).fit(df[features])
df["if_flag"] = model.predict(df[features]) == -1
print("Isolation Forest flagged:", int(df["if_flag"].sum()), "of", len(df))
