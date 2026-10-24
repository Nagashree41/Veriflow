"""
classify.py  -  VeriFlow "Brain", part 2 of 3
Steps: Check evidence + Classify case.

Takes the numbers from detect.py plus the complaint count and decides which of
the 4 classes a case belongs to, with human-readable reasons.
"""

NORMAL = "Normal"
FAULT = "Sensor Fault Suspected"
VERIFY = "Needs Verification"
INCIDENT = "Potential Incident"
LABELS = [NORMAL, FAULT, VERIFY, INCIDENT]    # reuse these in evaluate.py

# ---------------------------------------------------------------- settings
R_UNRELIABLE = 0.5        # R < 0.5  -> sensor unreliable
R_INCIDENT = 0.6          # incident needs R >= 0.6
MIN_CONSECUTIVE = 3       # 3+ consecutive flags = persistent
SUPPORT_COMPLAINTS = 2    # 2+ complaints count as support
VERIFY_COMPLAINTS = 3     # 3+ complaints with normal sensors -> verify
Z_EXTREME = 6.0           # |z| >= 6 can stand in for "support"


def count_partner_flags(results: dict, param: str) -> int:
    """How many OTHER parameters at this location are currently flagged.
    Only counts partners whose own sensor is reliable."""
    return sum(
        1
        for p, r in results.items()
        if p != param and r["consecutive_flags"] >= 1 and r["R"] >= R_UNRELIABLE
    )


def classify_case(R, consecutive_flags, flags_in_window, mean_abs_z,
                  partner_flagged, complaints_2h, transient_spikes=0,
                  check_complaints_only=True, p_breach=0.0,
                  limit_alarm=False, limit_reasons=None):
    """Return (label, reasons). Rules are checked in this order."""
    anomaly = flags_in_window > 0
    support = partner_flagged >= 1 or complaints_2h >= SUPPORT_COMPLAINTS

    # 1) Unreliable sensor: fault unless something else backs the reading up
    if R < R_UNRELIABLE:
        if not support:
            return FAULT, [f"Sensor reliability R={R:.2f} is below {R_UNRELIABLE}",
                           "No partner parameter or complaints corroborate it"]
        return VERIFY, [f"Sensor reliability R={R:.2f} is low, but other evidence disagrees "
                        "with a pure sensor fault"]

    if limit_alarm and R >= R_INCIDENT:
        reasons = list(limit_reasons or [])
        if p_breach >= 0.5:
            reasons.append(f"Absolute-limit breach probability is {p_breach:.1%}; incident does not need persistence")
            return INCIDENT, reasons
        reasons.append("Absolute-limit warning needs verification")
        return VERIFY, reasons

    # A one-reading jump that immediately returned to normal is deliberately
    # ignored.  It is logged by validation but must not become a water alarm.
    if anomaly and consecutive_flags == 0 and transient_spikes and not support:
        return NORMAL, ["Transient spike returned to baseline without corroboration"]

    # 2) Persistent + trusted + (supported or extreme)
    persistent = consecutive_flags >= MIN_CONSECUTIVE and R >= R_INCIDENT
    extreme = mean_abs_z >= Z_EXTREME
    if persistent and (support or extreme):
        reasons = [f"{consecutive_flags} consecutive flagged readings (mean |z| {mean_abs_z:.1f})",
                   f"Sensor reliability R={R:.2f}"]
        if partner_flagged:
            reasons.append(f"{partner_flagged} partner parameter(s) also flagged")
        if complaints_2h:
            reasons.append(f"{complaints_2h} complaint(s) in the last 2 h")
        if extreme and not support:
            reasons.append(f"Extreme severity (mean |z| >= {Z_EXTREME:g}) without other support")
        return INCIDENT, reasons

    # 3) Anomaly, but evidence is thin
    if anomaly:
        reasons = [f"Flagged reading(s) in the last window (run of {consecutive_flags})"]
        if consecutive_flags < MIN_CONSECUTIVE:
            reasons.append(f"Not persistent yet (needs {MIN_CONSECUTIVE}+ consecutive)")
        elif R < R_INCIDENT:
            reasons.append(f"R={R:.2f} is under {R_INCIDENT} needed for an incident")
        else:
            reasons.append("No partner parameter or enough complaints to support it")
        return VERIFY, reasons

    # 4) No anomaly, but people are complaining
    if check_complaints_only and complaints_2h >= VERIFY_COMPLAINTS:
        return VERIFY, [f"{complaints_2h} complaints in the last 2 h while sensors look normal"]

    return NORMAL, ["No flagged readings and sensor reliable"]


def classify_location(results: dict, complaints_2h: int = 0) -> list:
    """results = detect.detect_location(...) output for one location.
    Returns one case dict per parameter that is NOT Normal, plus a single
    'Complaints' case when only complaints raise the concern."""
    cases = []
    for param, r in results.items():
        partner = count_partner_flags(results, param)
        label, reasons = classify_case(
            r["R"], r["consecutive_flags"], r["flags_in_window"], r["mean_abs_z"],
            partner, complaints_2h, r.get("transient_spikes", 0), check_complaints_only=False,
            p_breach=r.get("p_breach", 0.0), limit_alarm=r.get("limit_alarm", False),
            limit_reasons=r.get("limit_reasons"))
        if label != NORMAL:
            cases.append({
                "parameter": param, "label": label, "reasons": reasons,
                "R": r["R"], "consecutive_flags": r["consecutive_flags"],
                "mean_abs_z": r["mean_abs_z"], "partner_flagged": partner,
                "complaints_2h": complaints_2h, "direction": r["direction"],
                "p_breach": r.get("p_breach", 0.0), "severity": r.get("severity", 0.0),
                "limit_alarm": r.get("limit_alarm", False),
            })

    if not cases and complaints_2h >= VERIFY_COMPLAINTS:
        cases.append({
            "parameter": "Complaints", "label": VERIFY,
            "reasons": [f"{complaints_2h} complaints in the last 2 h while sensors look normal"],
            "R": min(r["R"] for r in results.values()) if results else 1.0,
            "consecutive_flags": 0, "mean_abs_z": 0.0, "partner_flagged": 0,
            "complaints_2h": complaints_2h, "direction": None,
        })
    return cases


# ------------------------------------------------------------------- demo
if __name__ == "__main__":
    print(classify_case(R=0.31, consecutive_flags=1, flags_in_window=1,
                        mean_abs_z=6.0, partner_flagged=0, complaints_2h=0))
    print(classify_case(R=0.96, consecutive_flags=6, flags_in_window=6,
                        mean_abs_z=4.8, partner_flagged=1, complaints_2h=2))
    print(classify_case(R=0.95, consecutive_flags=0, flags_in_window=0,
                        mean_abs_z=0.0, partner_flagged=0, complaints_2h=3))
