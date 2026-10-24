import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score, confusion_matrix
from sklearn.ensemble import IsolationForest

labels = ["Normal", "Sensor Fault", "Needs Verification", "Potential Incident"]
N, SF, NV, PI = labels

# --- Placeholder data (replace with your generator and VeriFlow output) ---
y_true     = [N, N,  SF, SF, NV, PI, PI, N, SF, PI]   # ground truth
y_veriflow = [N, N,  SF, NV, NV, PI, PI, N, SF, PI]   # VeriFlow predictions
y_baseline = [N, PI, PI, PI, N,  PI, PI, N, PI, PI]   # threshold-only predictions

from sklearn.metrics import precision_score, recall_score, confusion_matrix

labels = ["Normal", "Sensor Fault", "Needs Verification", "Potential Incident"]

# y_true: ground-truth labels from your seeded generator
# y_veriflow: classes predicted by your VeriFlow rules
# y_baseline: classes predicted by the single-threshold baseline

for name, y_pred in [("VeriFlow", y_veriflow), ("Threshold", y_baseline)]:
    p = precision_score(y_true, y_pred, labels=["Potential Incident"],
                        average="macro", zero_division=0)
    r = recall_score(y_true, y_pred, labels=["Potential Incident"],
                     average="macro", zero_division=0)
    print(name, "precision:", p, "recall:", r)
    print(confusion_matrix(y_true, y_pred, labels=labels))

from sklearn.ensemble import IsolationForest

model = IsolationForest(contamination=0.05, random_state=42)
model.fit(df[["ph", "turbidity", "tds", "chlorine"]])
df["if_flag"] = model.predict(df[["ph", "turbidity", "tds", "chlorine"]]) == -1

# --- Optional: Isolation Forest on placeholder sensor data ---
rng = np.random.default_rng(42)
df = pd.DataFrame({
    "ph":        rng.normal(7.2, 0.2, 200),
    "turbidity": rng.normal(1.0, 0.3, 200),
    "tds":       rng.normal(300, 20, 200),
    "chlorine":  rng.normal(1.5, 0.2, 200),
})

features = ["ph", "turbidity", "tds", "chlorine"]
model = IsolationForest(contamination=0.05, random_state=42)
model.fit(df[features])
df["if_flag"] = model.predict(df[features]) == -1
print("Isolation Forest flagged:", df["if_flag"].sum(), "of", len(df))