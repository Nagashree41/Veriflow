"""
bridge.py - adapter between the backend (Persons 1-3) and the dashboard (app.py).

app.py is NOT modified.  It expects three tables from load_demo_data() plus a DETAILS
dict, all filled with dummy numbers.  This module builds the same things from the real
pipeline output and swaps them in at run time (see veriflow_app.py, which installs the hooks).

    simulator.py -> data/*.csv
    pipeline.py  -> data/processed/{ranked_alerts,site_decisions,sensor_reliability}.csv
    bridge.py    -> sites / readings / queue tables + DETAILS text + baseline calibration

Tables (exact columns app.py reads):
    sites    : site, lat, lon, status, score
    readings : timestamp, site, parameter, value, flagged
    queue    : Site, Time, Parameter, Status, Score, Priority

Run `python bridge.py` to check the adapter without starting Streamlit.
"""
from __future__ import annotations

import ast
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "processed"

# backend column name -> parameter name the dashboard uses (PARAMETER_LIBRARY["Water"] keys)
PARAM_NAME = {"ph": "pH", "turbidity": "turbidity", "tds": "TDS", "chlorine": "chlorine"}
PARAM_ORDER = list(PARAM_NAME.values())

ACTIONS = {
    "Potential Incident": ["Check sensor", "Collect confirmatory sample", "Escalate for human review"],
    "Needs Verification": ["Recheck readings", "Collect a sample"],
    "Sensor Fault Suspected": ["Add to maintenance list", "Inspect / clean sensor"],
}


# ---------------------------------------------------------------------------
# 1. Make sure the backend outputs exist and are fresh
# ---------------------------------------------------------------------------
def ensure_data(force: bool = False) -> None:
    """Generate data (simulator) and run the pipeline when files are missing or stale."""
    import pipeline
    import simulator

    readings = DATA_DIR / "readings.csv"
    if force or not all((DATA_DIR / f).exists() for f in
                        ("readings.csv", "sites.csv", "complaints.csv", "labels.csv")):
        simulator.save(*simulator.generate(), folder=str(DATA_DIR))

    needed = [OUT_DIR / f for f in ("ranked_alerts.csv", "site_decisions.csv", "sensor_reliability.csv")]
    stale = any(not p.exists() or p.stat().st_mtime < readings.stat().st_mtime for p in needed)
    if force or stale:
        pipeline.run_pipeline(str(readings), str(DATA_DIR / "complaints.csv"),
                              str(DATA_DIR / "sites.csv"), str(OUT_DIR))


def _signature() -> tuple:
    """Changes whenever the data or the pipeline output changes (cache key)."""
    files = [DATA_DIR / "readings.csv", OUT_DIR / "ranked_alerts.csv", OUT_DIR / "site_decisions.csv"]
    return tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in files)


# ---------------------------------------------------------------------------
# 2. Build the dashboard tables
# ---------------------------------------------------------------------------
def _param_label(col: str) -> str:
    return PARAM_NAME.get(col, col.title() if col.islower() else col)


def _build_readings(raw: pd.DataFrame, names: dict) -> pd.DataFrame:
    """Long table with a `flagged` column from the same modified z-score the detector uses."""
    from main.detect import Z_FLAG, rolling_modified_z

    parts = []
    for site_id, group in raw.groupby("site_id", sort=True):
        group = group.sort_values("timestamp", kind="stable")
        for col, label in PARAM_NAME.items():
            if col not in group.columns:
                continue
            values = group[col].astype(float).reset_index(drop=True)
            flags = (rolling_modified_z(values).abs() >= Z_FLAG).fillna(False).to_numpy()
            parts.append(pd.DataFrame({
                "timestamp": group["timestamp"].to_numpy(),
                "site": names[site_id], "parameter": label,
                "value": values.to_numpy(), "flagged": flags.astype(bool)}))
    df = pd.concat(parts, ignore_index=True)
    df["parameter"] = pd.Categorical(df["parameter"], PARAM_ORDER, ordered=True)
    df = df.sort_values(["site", "parameter", "timestamp"], kind="stable")
    df["parameter"] = df["parameter"].astype(str)
    return df.reset_index(drop=True)


def _calibration(raw: pd.DataFrame) -> dict:
    """Normal level and normal wobble per parameter, measured from the data itself.

    app.py scores every reading as (value - typical) / noise using its PARAMETER_LIBRARY.
    Its built-in numbers were made for different dummy data, so we overwrite them with the
    robust median and 1.4826*MAD of the real readings (outliers cannot skew them).
    """
    out = {}
    for col, label in PARAM_NAME.items():
        v = raw[col].astype(float).dropna()
        if v.empty:
            continue
        med = float(v.median())
        mad = float((v - med).abs().median())
        out[label] = {"typical": round(med, 3), "noise": round(max(1.4826 * mad, 1e-3), 3)}
    return out


def _details(ranked: pd.DataFrame, reliab: pd.DataFrame, names: dict) -> dict:
    """Text for the 'why flagged' box and the pop-up, one entry per site with a case."""
    details = {}
    if ranked.empty:
        return details
    for site_id, cases in ranked.groupby("site_id", sort=False):
        site = names[site_id]
        top = cases.iloc[0]
        why = []
        for c in cases.itertuples():
            reasons = ast.literal_eval(c.reasons) if isinstance(c.reasons, str) else list(c.reasons)
            tag = _param_label(c.parameter)
            if isinstance(c.direction, str):
                tag += f" {c.direction}"
            why.append(f"{tag}: {reasons[0]}")
        top_reasons = ast.literal_eval(top.reasons) if isinstance(top.reasons, str) else list(top.reasons)
        why += [r for r in top_reasons[1:] if r not in why]
        # data-quality evidence from validate.py
        rel = reliab[reliab["site_id"] == site_id]
        for r in rel.itertuples():
            bits = []
            if r.stuck:
                bits.append("value stuck (same reading 8+ times)")
            if r.missing_count:
                bits.append(f"{r.missing_count} missing reading(s)")
            if r.impossible_count:
                bits.append(f"{r.impossible_count} impossible value(s)")
            if r.spike_count:
                bits.append(f"{r.spike_count} spike(s) that snapped back")
            if bits:
                why.append(f"{_param_label(r.sensor)} sensor: " + ", ".join(bits) + f" (R {r.reliability:.2f})")
        details[site] = {"why": why, "actions": ACTIONS.get(top.label, ["Review"])}
    return details


@lru_cache(maxsize=2)
def _artifacts(signature: tuple) -> dict:
    sites_df = pd.read_csv(DATA_DIR / "sites.csv")
    raw = pd.read_csv(DATA_DIR / "readings.csv", parse_dates=["timestamp"])
    ranked = pd.read_csv(OUT_DIR / "ranked_alerts.csv")
    decisions = pd.read_csv(OUT_DIR / "site_decisions.csv")
    reliab = pd.read_csv(OUT_DIR / "sensor_reliability.csv")
    names = sites_df.set_index("site_id")["name"].to_dict()

    top_score = ranked.groupby("site_id")["score"].max().to_dict() if not ranked.empty else {}
    status = decisions.set_index("site_id")["decision"].to_dict()
    sites = pd.DataFrame({
        "site": sites_df["name"],
        "lat": sites_df["lat"].astype(float),
        "lon": sites_df["lng"].astype(float),
        "status": [status.get(i, "Normal") for i in sites_df["site_id"]],
        "score": [int(top_score.get(i, 0)) for i in sites_df["site_id"]],
    })

    end = raw.groupby("site_id")["timestamp"].max().to_dict()
    queue = pd.DataFrame({
        "Site": [names[i] for i in ranked["site_id"]],
        "Time": [end[i].strftime("%H:%M") for i in ranked["site_id"]],
        "Parameter": [_param_label(p) for p in ranked["parameter"]],
        "Status": ranked["label"],
        "Score": ranked["score"].astype(int),
        "Priority": ranked["priority"],
    }) if not ranked.empty else pd.DataFrame(
        columns=["Site", "Time", "Parameter", "Status", "Score", "Priority"])

    return {"sites": sites, "readings": _build_readings(raw, names), "queue": queue,
            "details": _details(ranked, reliab, names), "calibration": _calibration(raw)}


def load_pipeline_data():
    """Drop-in replacement for app.load_demo_data(): returns (sites, readings, queue)."""
    ensure_data()
    art = _artifacts(_signature())
    apply_app_patches()
    return art["sites"].copy(), art["readings"].copy(), art["queue"].copy()


# ---------------------------------------------------------------------------
# 3. Run-time hooks (app.py is re-executed on every Streamlit rerun, so its module-level
#    dicts are fresh each time and must be refilled each time)
# ---------------------------------------------------------------------------
def _app_namespace():
    """Globals of the running app.py (found by walking up the call stack)."""
    frame = sys._getframe(1)
    while frame is not None:
        g = frame.f_globals
        if "PARAMETER_LIBRARY" in g and "DETAILS" in g:
            return g
        frame = frame.f_back
    return None


def apply_app_patches() -> None:
    """Fill app.DETAILS and calibrate app.PARAMETER_LIBRARY from the real pipeline output."""
    ns = _app_namespace()
    if ns is None:
        return
    art = _artifacts(_signature())
    water = ns["PARAMETER_LIBRARY"]["Water"]
    for label, cal in art["calibration"].items():
        if label in water:
            water[label]["typical"] = cal["typical"]
            water[label]["noise"] = cal["noise"]
    ns["DETAILS"].clear()
    ns["DETAILS"].update(art["details"])


def install_hooks(st, style) -> None:
    """Called by veriflow_app.py before app.py runs.  Idempotent.

    1. st.cache_data on `load_demo_data` is replaced by load_pipeline_data (so the dashboard
       reads the real tables).  Every other cached function is untouched.
    2. style.inject_css (called by app.py on every rerun, right after init_state) also
       re-applies the DETAILS text and parameter calibration for that rerun.
    """
    if not getattr(st.cache_data, "_vf_patched", False):
        original = st.cache_data

        def cache_data(*args, **kwargs):
            def decorate(fn):
                if getattr(fn, "__name__", "") == "load_demo_data":
                    return load_pipeline_data
                return original(*args, **kwargs)(fn)
            if len(args) == 1 and callable(args[0]) and not kwargs:   # bare @st.cache_data
                fn, args = args[0], ()
                return decorate(fn)
            return decorate

        cache_data._vf_patched = True
        for attr in ("clear",):
            if hasattr(original, attr):
                setattr(cache_data, attr, getattr(original, attr))
        st.cache_data = cache_data

    if not getattr(style.inject_css, "_vf_patched", False):
        original_css = style.inject_css

        def inject_css():
            apply_app_patches()
            return original_css()

        inject_css._vf_patched = True
        style.inject_css = inject_css


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ensure_data()
    art = _artifacts(_signature())
    pd.set_option("display.width", 200)
    print("SITES\n", art["sites"], "\n\nQUEUE\n", art["queue"])
    print("\nREADINGS", art["readings"].shape, "flagged:", int(art["readings"]["flagged"].sum()))
    print("\nCALIBRATION", art["calibration"])
    for site, d in art["details"].items():
        print(f"\nDETAILS {site}")
        for line in d["why"]:
            print("  -", line)
        print("  actions:", d["actions"])
