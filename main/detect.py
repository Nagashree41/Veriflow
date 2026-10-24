"""
detect.py  -  VeriFlow "Brain", part 1 of 3
Steps: Validate (sensor reliability R) + Detect (rolling modified z-score).

Input : a pandas Series of readings for ONE parameter at ONE location,
        oldest first, one row per reading (5-minute spacing assumed).
Output: a dict of numbers that classify.py and score.py consume.
"""
import numpy as np
import pandas as pd
import math

# ---------------------------------------------------------------- settings
# From the slides
Z_FLAG = 3.5              # flag a reading when |z| >= 3.5
PERSISTENCE_WINDOW = 6    # last 6 readings (30 min)
RELIABILITY_WINDOW = 24   # R uses the last 24 readings
STUCK_RUN = 8             # 8+ identical readings = stuck
SPIKE_REVERT_WITHIN = 2   # a jump that snaps back within 2 readings

# My own choices (not on the slides) - tune or justify these
BASELINE_WINDOW = 48      # 48 readings = 4 h of history for median/MAD
MIN_BASELINE = 12         # need at least this many past readings first

# Physically possible ranges. Adjust to match your simulator's units.
PHYSICAL_RANGES = {
    "ph": (0.0, 14.0),
    "turbidity": (0.0, 1000.0),   # NTU
    "tds": (0.0, 5000.0),         # mg/L
    "chlorine": (0.0, 10.0),      # mg/L
}

# Placeholder limits and sensor errors; confirm from sensor datasheet and water-quality standard.
SAFE_LIMITS = {
    "ph": {"low": 6.5, "high": 8.5, "sigma": 0.05},
    "turbidity": {"low": None, "high": 5.0, "sigma": 0.2},
    "tds": {"low": None, "high": 500.0, "sigma": 10.0},
    "chlorine": {"low": 0.2, "high": 4.0, "sigma": 0.05},
}
P_ALERT = 0.05
CUSUM_K_FRAC = 0.5
CUSUM_H_FRAC = 5.0
TREND_WINDOW = 12
RESPONSE_READINGS = 6
LOGISTIC_CLIP = 60.0
GUARD_BAND_Z = 1.6448536269514722  # one-sided normal quantile for P_ALERT


# ------------------------------------------------------------ anomaly part
def rolling_modified_z(values: pd.Series) -> pd.Series:
    """Modified z-score against a rolling median/MAD baseline.

    The baseline is built from PAST readings only (shift(1)), so a reading
    cannot hide itself by dragging the median toward its own value.
    """
    x = values.astype(float)
    past = x.shift(1)
    roll = past.rolling(BASELINE_WINDOW, min_periods=MIN_BASELINE)

    median = roll.median()
    mad = roll.apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)

    # Very flat data gives MAD ~ 0 and would make z explode; use a small floor.
    floor = 0.01 * median.abs() + 1e-6
    mad = mad.where(mad >= floor, floor)

    return 0.6745 * (x - median) / mad


def trailing_run(flags: pd.Series) -> int:
    """How many flagged readings in a row at the END of the series."""
    run = 0
    for f in reversed(flags.tolist()):
        if f:
            run += 1
        else:
            break
    return run


def breach_probability(x, limit, sigma, side):
    """Probability that measurement error places x beyond an absolute limit."""
    if pd.isna(x) or limit is None or not np.isfinite(sigma) or sigma <= 0:
        return 0.0
    z = ((limit - x) if side == "high" else (x - limit)) / sigma
    return float(min(1.0, max(0.0, 0.5 * math.erfc(z / math.sqrt(2.0)))) )


def severity_logistic(x, limit, sigma, side):
    """Smooth, bounded severity relative to an absolute limit."""
    if pd.isna(x) or limit is None or not np.isfinite(sigma) or sigma <= 0:
        return 0.0
    distance = (x - limit) if side == "high" else (limit - x)
    exponent = float(np.clip(-distance / sigma, -LOGISTIC_CLIP, LOGISTIC_CLIP))
    return float(1.0 / (1.0 + math.exp(exponent)))


def cusum(values, mu0, sigma):
    """Return upper/lower CUSUM paths, final alarm, and its direction."""
    x = pd.Series(values, dtype=float).reset_index(drop=True)
    k, h = CUSUM_K_FRAC * sigma, CUSUM_H_FRAC * sigma
    hi, lo, upper, lower = [], [], 0.0, 0.0
    for value in x:
        if pd.notna(value):
            upper = max(0.0, upper + value - mu0 - k)
            lower = max(0.0, lower + mu0 - value - k)
        hi.append(upper)
        lo.append(lower)
    alarm_hi, alarm_lo = upper > h, lower > h
    direction = "high" if alarm_hi and (not alarm_lo or upper >= lower) else "low" if alarm_lo else None
    return pd.Series(hi, index=x.index), pd.Series(lo, index=x.index), bool(alarm_hi or alarm_lo), direction


def time_to_limit(values, limit, side, window=TREND_WINDOW):
    """Estimate readings remaining to a limit from the recent least-squares slope."""
    valid = pd.Series(values, dtype=float).dropna().tail(window)
    if limit is None or len(valid) < 4:
        return float("inf")
    last = float(valid.iloc[-1])
    if (side == "high" and last >= limit) or (side == "low" and last <= limit):
        return 0.0
    slope = float(np.polyfit(np.arange(len(valid)), valid.to_numpy(), 1)[0])
    toward = slope > 0 if side == "high" else slope < 0
    if not toward:
        return float("inf")
    return max(0.0, float((limit - last) / slope))


def limit_check(values, param, limits=None):
    """Combine absolute-limit probability, severity, drift, and response-time checks."""
    x = pd.Series(values, dtype=float).reset_index(drop=True)
    cfg = (SAFE_LIMITS if limits is None else limits).get(param)
    if cfg is None:
        cfg = {"low": None, "high": None, "sigma": 1.0}
    sigma = float(cfg["sigma"])
    valid = x.dropna()
    latest = float(valid.iloc[-1]) if len(valid) else float("nan")
    sides = [(side, cfg.get(side)) for side in ("low", "high") if cfg.get(side) is not None]
    probs = [(breach_probability(latest, lim, sigma, side), side, lim)
             for side, lim in sides]
    p_breach, p_side, p_limit = max(probs, default=(0.0, None, None))
    severity = max((severity_logistic(latest, lim, sigma, side) for side, lim in sides), default=0.0)
    baseline = float(valid.iloc[:MIN_BASELINE].median()) if len(valid) else 0.0
    hi, lo, c_alarm, c_direction = cusum(x, baseline, sigma)
    times = [(time_to_limit(x, lim, side), side, lim) for side, lim in sides]
    t_limit, t_side, t_value = min(times, default=(float("inf"), None, None))
    reasons = []
    if p_breach >= P_ALERT:
        guard = p_limit - GUARD_BAND_Z * sigma if p_side == "high" else p_limit + GUARD_BAND_Z * sigma
        verb = "exceeding" if p_side == "high" else "falling below"
        reasons.append(f"Reading {latest:g} has {p_breach:.1%} chance of {verb} the {p_limit:g} limit (guard band starts at {guard:g})")
    if c_alarm:
        reasons.append(f"CUSUM detected sustained {c_direction} drift from baseline {baseline:g}")
    if t_limit < RESPONSE_READINGS:
        reasons.append(f"Trend may reach the {t_value:g} {t_side} limit in {t_limit:.1f} readings")
    return {"p_breach": p_breach, "severity": severity, "cusum_alarm": c_alarm,
            "cusum_direction": c_direction, "time_to_limit": t_limit,
            "limit_alarm": bool(p_breach >= P_ALERT or c_alarm or t_limit < RESPONSE_READINGS),
            "limit_reasons": reasons, "cusum_hi": hi, "cusum_lo": lo}


# ---------------------------------------------------------- reliability part
def has_stuck_run(x: pd.Series) -> bool:
    """True if 8+ identical non-missing readings in a row."""
    run, prev = 0, None
    for v in x:
        if pd.notna(v) and v == prev:
            run += 1
        else:
            run = 1 if pd.notna(v) else 0
        prev = v
        if run >= STUCK_RUN:
            return True
    return False


def count_spike_reversals(flags: pd.Series) -> int:
    """Count flagged bursts of 1-2 readings that were followed by normal readings."""
    f = flags.fillna(False).astype(bool).tolist()
    count, i = 0, 0
    while i < len(f):
        if f[i]:
            j = i
            while j < len(f) and f[j]:
                j += 1
            run_len = j - i
            reverted = j < len(f)          # a normal reading came after the burst
            if run_len <= SPIKE_REVERT_WITHIN and reverted:
                count += 1
            i = j
        else:
            i += 1
    return count


def sensor_reliability(values: pd.Series, flags: pd.Series, param: str) -> dict:
    """R = 1 - min(1, penalty), over the last 24 readings.

    penalty = 1.0*missing + 1.0*out_of_range + 0.4*stuck + 3.0*spike_reversal
    """
    recent = values.astype(float).tail(RELIABILITY_WINDOW)
    recent_flags = flags.tail(RELIABILITY_WINDOW)
    n = len(recent)
    if n == 0:
        return {"R": 0.0, "missing": 1.0, "out_of_range": 0.0, "stuck": 0.0, "spike_reversal": 0.0}

    lo, hi = PHYSICAL_RANGES[param]
    missing = recent.isna().sum() / n
    out_of_range = ((recent < lo) | (recent > hi)).sum() / n    # NaN compares False
    stuck = 1.0 if has_stuck_run(recent) else 0.0               # 0 or 1, as on the slide
    spike_rev = count_spike_reversals(recent_flags) / n

    penalty = 1.0 * missing + 1.0 * out_of_range + 0.4 * stuck + 3.0 * spike_rev
    return {
        "R": float(1 - min(1.0, penalty)),
        "missing": float(missing),
        "out_of_range": float(out_of_range),
        "stuck": stuck,
        "spike_reversal": float(spike_rev),
    }


# ------------------------------------------------------------- main entry
def analyze_series(values: pd.Series, param: str, reliability: float | None = None, limits=None) -> dict:
    """Run detection on one parameter, using validator ``reliability`` when supplied."""
    values = values.astype(float).reset_index(drop=True)
    z = rolling_modified_z(values)
    flags = z.abs() >= Z_FLAG                      # NaN -> False

    run = trailing_run(flags)
    run_z = z.iloc[len(z) - run:] if run else z.iloc[0:0]
    run_z = run_z.tail(PERSISTENCE_WINDOW)

    rel = sensor_reliability(values, flags, param)
    # ``validate.py`` is the canonical reliability implementation.  Retaining
    # this fallback keeps the module useful on a standalone Series demo.
    R = rel["R"] if reliability is None else float(reliability)
    limit = limit_check(values, param, limits)
    return {
        "param": param,
        "R": R,
        "reliability_detail": rel,
        "consecutive_flags": run,
        "flags_in_window": int(flags.tail(PERSISTENCE_WINDOW).sum()),
        "mean_abs_z": float(run_z.abs().mean()) if run else 0.0,
        "direction": ("high" if run_z.mean() > 0 else "low") if run else None,
        "latest_value": None if values.empty else values.iloc[-1],
        "z": z,          # full series, handy for the dashboard trend charts
        "flags": flags,
        **limit,
    }


def detect_location(df: pd.DataFrame, parameters=None, reliabilities: dict | None = None, limits=None) -> dict:
    """df = readings for ONE location (one column per parameter, oldest first).
    Returns {parameter: analyze_series(...) result}."""
    parameters = parameters or [c for c in df.columns if c in PHYSICAL_RANGES]
    reliabilities = reliabilities or {}
    return {p: analyze_series(df[p], p, reliabilities.get(p), limits) for p in parameters}


# ------------------------------------------------------------------- demo
if __name__ == "__main__":
    rng = np.random.default_rng(0)
    n = 80
    chlorine = rng.normal(1.5, 0.05, n)
    chlorine[-6:] -= 0.5                       # persistent drop, last 6 readings
    spike = rng.normal(7.2, 0.05, n)
    spike[60] += 3.0                           # single spike that snaps back
    stuck = rng.normal(300, 5, n)
    stuck[-10:] = stuck[-10]                   # sensor frozen for 10 readings

    demo = pd.DataFrame({"chlorine": chlorine, "ph": spike, "tds": stuck})
    for p, r in detect_location(demo).items():
        print(f"{p:9s} R={r['R']:.2f}  run={r['consecutive_flags']}  "
              f"mean|z|={r['mean_abs_z']:.1f}  dir={r['direction']}")
