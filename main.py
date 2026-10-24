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