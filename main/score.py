"""
score.py  -  VeriFlow "Brain", part 3 of 3
Steps: Score + Rank.

Evidence Score (0-100) = 100 * R * (0.35*S + 0.30*P + 0.20*X + 0.15*C)
It RANKS and EXPLAINS cases. It is NOT a probability of contamination.
"""
from classify import NORMAL, FAULT, VERIFY, INCIDENT

WEIGHTS = {"S": 0.35, "P": 0.30, "X": 0.20, "C": 0.15}   # design choices, not validated
PERSISTENCE_WINDOW = 6
Z_SCALE = 6.0
PARTNER_SCALE = 2
COMPLAINT_SCALE = 3


def _cap(v: float) -> float:
    return max(0.0, min(1.0, v))


def evidence_score(R, mean_abs_z, consecutive_flags, partner_flagged, complaints_2h) -> dict:
    """Pass None for partner_flagged / complaints_2h when that evidence is unavailable:
    it counts as 0 and is listed under 'limited'."""
    limited = []
    if partner_flagged is None:
        partner_flagged = 0
        limited.append("partner parameters")
    if complaints_2h is None:
        complaints_2h = 0
        limited.append("complaints")

    S = _cap(mean_abs_z / Z_SCALE)                    # severity
    P = _cap(consecutive_flags / PERSISTENCE_WINDOW)  # persistence
    X = _cap(partner_flagged / PARTNER_SCALE)         # partner support
    C = _cap(complaints_2h / COMPLAINT_SCALE)         # complaints

    raw = 100 * R * (WEIGHTS["S"] * S + WEIGHTS["P"] * P + WEIGHTS["X"] * X + WEIGHTS["C"] * C)
    return {"score": round(raw), "score_raw": raw,
            "S": S, "P": P, "X": X, "C": C, "limited": limited}


# ------------------------------------------------------------------ ranking
PRIORITY = {INCIDENT: "P1", VERIFY: "P2", FAULT: "Maint."}
_TIER = {"P1": 0, "P2": 1, "Maint.": 2}


def rank_cases(cases: list, sensitivity: dict = None, default_sensitivity: float = 0.5) -> list:
    """cases: dicts from classify.classify_location, each with a 'location' key added
    by the caller. sensitivity: {location: 0..1} (e.g. hospital/school = high).

    Order: P1, then P2, then Maintenance; inside a tier, by
    Evidence Score x (0.7 + 0.3 x location sensitivity), highest first.
    Normal cases are dropped."""
    sensitivity = sensitivity or {}
    ranked = []
    for c in cases:
        if c["label"] == NORMAL:
            continue
        ev = evidence_score(c["R"], c["mean_abs_z"], c["consecutive_flags"],
                            c.get("partner_flagged"), c.get("complaints_2h"))
        sens = sensitivity.get(c.get("location"), default_sensitivity)
        adjusted = ev["score_raw"] * (0.7 + 0.3 * sens)
        ranked.append({**c, **ev, "priority": PRIORITY[c["label"]],
                       "adjusted_score": adjusted})

    ranked.sort(key=lambda c: (_TIER[c["priority"]], -c["adjusted_score"]))
    return ranked


# ------------------------------------------------------------------- demo
if __name__ == "__main__":
    # Worked examples from slide 6 - these should print 12 and 75
    a = evidence_score(R=0.31, mean_abs_z=6.0, consecutive_flags=1, partner_flagged=0, complaints_2h=0)
    b = evidence_score(R=0.96, mean_abs_z=4.8, consecutive_flags=6, partner_flagged=1, complaints_2h=2)
    print("Example A score:", a["score"], "(slide says 12)")
    print("Example B score:", b["score"], "(slide says 75)")
