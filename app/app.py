"""
VeriFlow - multi-page Streamlit app (prototype, SIMULATED DATA)

Pages
  welcome    : project name, site dropdown, "Add new site"; Log in / Sign up at top right
  auth       : log in / sign up (accounts stored hashed in users.json)
  dashboard  : (login required) cards, map, live trends, queue, alert detail, then
               reading-level bars, live bar graphs, sensor registry, water-level tanks
  add_site   : (login required) register a new site / sensor

Needs Streamlit >= 1.39 (fragments for live refresh, keyed containers for the pop-up):
    pip install -U streamlit plotly pandas numpy
Run:
    streamlit run app.py

Where to plug in the real pipeline later
  * load_demo_data()    -> return the real sites / readings / queue tables
  * level_z()           -> use the pipeline's own z-score column if you prefer
  * sites["status"]     -> the "immediate attention" pop-up reads this ("Potential Incident")
  * st.session_state.configs[site] holds every per-site setting from the Add-site form
"""
import hashlib
import hmac
import html
import inspect
import json
import math
import os
import re
import threading
import time
import zlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as pgo   # NOTE: not "go" -> go() is the navigation function below
import streamlit as st
from plotly.subplots import make_subplots

import maps
from style import (BAND_COLORS, BAND_EMOJI, ORANGE, STATUS_COLORS, T, inject_css,
                   style_figure)

st.set_page_config(page_title="VeriFlow", page_icon="🏮", layout="wide")

# Colours, fonts and CSS live in style.py (see DESIGN.md). Do not hard-code them here.

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
USERS_FILE = Path(__file__).with_name("users.json")
PBKDF2_ROUNDS = 200_000
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 300
SEED_DEMO_USER = True                      # set False to remove the demo account
DEMO_EMAIL = "demo@veriflow.app"
DEMO_PASSWORD = "Demo@1234"
ROLES = ["Control-room operator", "Field sampling team", "Campus / municipal water manager", "Other"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ALERT_MIN_SCORE = 60        # "genuine big threat" = status Potential Incident AND score >= this
STUCK_RUN = 8               # 8+ identical readings = stuck sensor
PERSIST_RUN = 8             # fault lasting 8+ readings (40 min) = persistently faulty
SPIKE_JUMP_SIGMA = 6        # jump of 6 sigma that snaps back = spike-reversal fault
MAX_POINTS_PER_SERIES = 288 # keep 24 h of history per sensor channel
LIVE_INTERVALS = [1, 2, 3, 5, 10, 15, 30]
PROTECTED_PAGES = ("dashboard", "add_site")

# Widget-bound keys: must exist on EVERY run (Streamlit drops them when the widget is not shown)
WIDGET_DEFAULTS = {
    "ui_live_on": True,
    "ui_live_interval": 3,
    "ui_live_points": 20,
    "ui_auth_mode": "Log in",
    "ui_tank_scope": "This site",
    "ui_reg_filter": "All",
}

# ---------------------------------------------------------------------------
# Static options for the add-site form
# ---------------------------------------------------------------------------
# unit, typical (simulation baseline), noise (simulation wobble), vmin/vmax (valid range)
PARAMETER_LIBRARY = {
    "Water": {
        "pH": dict(unit="pH", typical=7.2, noise=0.05, vmin=0.0, vmax=14.0),
        "turbidity": dict(unit="NTU", typical=1.0, noise=0.1, vmin=0.0, vmax=1000.0),
        "TDS": dict(unit="mg/L", typical=250.0, noise=5.0, vmin=0.0, vmax=5000.0),
        "chlorine": dict(unit="mg/L", typical=1.5, noise=0.08, vmin=0.0, vmax=10.0),
        "temperature": dict(unit="°C", typical=25.0, noise=0.3, vmin=0.0, vmax=50.0),
        "conductivity": dict(unit="µS/cm", typical=400.0, noise=8.0, vmin=0.0, vmax=5000.0),
        "dissolved oxygen": dict(unit="mg/L", typical=7.5, noise=0.15, vmin=0.0, vmax=20.0),
    },
    "Air": {
        "PM2.5": dict(unit="µg/m³", typical=35.0, noise=3.0, vmin=0.0, vmax=1000.0),
        "PM10": dict(unit="µg/m³", typical=70.0, noise=6.0, vmin=0.0, vmax=2000.0),
        "NO2": dict(unit="µg/m³", typical=25.0, noise=2.0, vmin=0.0, vmax=500.0),
        "SO2": dict(unit="µg/m³", typical=10.0, noise=1.0, vmin=0.0, vmax=500.0),
        "CO": dict(unit="mg/m³", typical=0.8, noise=0.1, vmin=0.0, vmax=50.0),
        "humidity": dict(unit="%", typical=55.0, noise=2.0, vmin=0.0, vmax=100.0),
        "air temperature": dict(unit="°C", typical=28.0, noise=0.5, vmin=-10.0, vmax=55.0),
    },
}
DEFAULT_PARAMS = {
    "Water": ["pH", "turbidity", "TDS", "chlorine"],
    "Air": ["PM2.5", "PM10", "NO2", "humidity"],
}
SITE_TYPES = {
    "Water": ["Treatment plant outlet", "Storage reservoir / tank", "Distribution pipeline",
              "Borehole / groundwater", "Campus water point", "River / lake intake"],
    "Air": ["Urban roadside", "Industrial zone", "Residential area",
            "Campus", "Traffic junction"],
}
SAMPLING_OPTIONS = [1, 5, 10, 15, 30, 60]

# Defaults come straight from the project slides.
DEFAULT_CRITERIA = dict(
    flag_z=3.5,             # flag a reading when |z| >= this
    persistence=3,          # consecutive flags needed for Potential Incident
    override_z=6.0,         # |z| at/above this can escalate without extra support
    r_unreliable=0.5,       # R below this = sensor unreliable
    r_incident=0.6,         # R needed for Potential Incident
    complaints_verify=3,    # complaints (sensors normal) -> Needs Verification
    complaints_support=2,   # complaints that count as support for an incident
    location_sensitivity=0.5,
    sampling_minutes=5,
    rated_life_months=36,   # sensor rated lifetime (for worn-out tracking)
)

DEMO_SITE_TYPES = ["Treatment plant outlet", "Storage reservoir / tank", "Distribution pipeline",
                   "Campus water point", "Borehole / groundwater", "Distribution pipeline",
                   "River / lake intake", "Storage reservoir / tank"]
# Simulated sensor ages in months (Site 6 and Site 8 are past their rated life)
DEMO_SENSOR_AGE_MONTHS = [8, 14, 11, 6, 20, 44, 17, 40]


# ---------------------------------------------------------------------------
# DUMMY DATA -> replace with the real pipeline output later.
# Must return 3 tables with these columns:
#   sites    : site, lat, lon, status, score
#   readings : timestamp, site, parameter, value, flagged (True/False)
#   queue    : Site, Time, Parameter, Status, Score, Priority
# ---------------------------------------------------------------------------
@st.cache_data
def load_demo_data():
    rng = np.random.default_rng(42)

    sites = pd.DataFrame({
        "site": [f"Site {i}" for i in range(1, 9)],
        "lat": [12.0, 12.4, 12.9, 12.2, 12.6, 12.1, 12.7, 12.5],
        "lon": [77.0, 77.6, 77.2, 77.9, 77.5, 77.3, 77.8, 77.1],
        "status": ["Normal", "Normal", "Potential Incident", "Normal",
                   "Needs Verification", "Sensor Fault Suspected",
                   "Normal", "Needs Verification"],
        "score": [0, 0, 75, 0, 15, 12, 0, 10],
    })

    water = PARAMETER_LIBRARY["Water"]
    params = DEFAULT_PARAMS["Water"]
    times = pd.date_range("2026-10-24 12:40", periods=24, freq="5min")  # last 2 h

    rows = []
    for site in sites["site"]:
        for p in params:
            vals = water[p]["typical"] + rng.normal(0, water[p]["noise"], len(times))
            flagged = np.zeros(len(times), dtype=bool)
            if site == "Site 3" and p == "chlorine":
                vals[-6:] -= 0.6
                flagged[-6:] = True
            if site == "Site 3" and p == "turbidity":
                vals[-4:] += np.array([0.3, 0.5, 0.7, 0.9])
                flagged[-4:] = True
            if site == "Site 6" and p == "turbidity":
                vals[-10:] = vals[-10]  # stuck sensor
                flagged[-10:] = True
            if site == "Site 2" and p == "pH":
                vals[-9] += 1.5         # single isolated spike (intermittent fault)
                flagged[-9] = True
            for t, v, f in zip(times, vals, flagged):
                rows.append((t, site, p, v, bool(f)))
    readings = pd.DataFrame(rows, columns=["timestamp", "site", "parameter", "value", "flagged"])

    queue = pd.DataFrame({
        "Site": ["Site 3", "Site 5", "Site 8", "Site 6"],
        "Time": ["14:35", "14:30", "14:25", "14:20"],
        "Parameter": ["Chlorine", "Complaints", "Complaints", "Turbidity"],
        "Status": ["Potential Incident", "Needs Verification",
                   "Needs Verification", "Sensor Fault Suspected"],
        "Score": [75, 15, 10, 12],
        "Priority": ["P1", "P2", "P2", "Maint."],
    })
    return sites, readings, queue


# Text for the "why flagged" box (dummy). Real version comes from the classifier.
DETAILS = {
    "Site 3": {
        "why": ["Chlorine low, 6 readings (mean |z| 4.8)",
                "Sensor reliability R 0.96",
                "Turbidity rising (support)",
                "2 simulated complaints (support)"],
        "actions": ["Check sensor", "Collect confirmatory sample", "Escalate for human review"],
    },
    "Site 5": {
        "why": ["3+ complaints in the last 2 h", "Sensors look normal"],
        "actions": ["Recheck readings", "Collect a sample"],
    },
    "Site 6": {
        "why": ["Turbidity value stuck (same reading 8+ times)", "Sensor reliability R 0.31",
                "No corroborating parameter"],
        "actions": ["Add to maintenance list", "Inspect / clean sensor"],
    },
}


# ===========================================================================
# AUTH (accounts in users.json, passwords hashed with salted PBKDF2-SHA256)
# ===========================================================================
@st.cache_resource
def _users_lock():
    return threading.Lock()


def _load_users():
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_users(users):
    tmp = USERS_FILE.with_name(USERS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(users, indent=2), encoding="utf-8")
    os.replace(tmp, USERS_FILE)


def _hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                               bytes.fromhex(salt_hex), PBKDF2_ROUNDS).hex()


def password_problems(pw):
    problems = []
    if len(pw) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", pw):
        problems.append("a letter")
    if not re.search(r"\d", pw):
        problems.append("a number")
    return problems


def register_user(name, email, role, password):
    email = email.strip().lower()
    with _users_lock():
        users = _load_users()
        if email in users:
            return False, "An account with this email already exists. Try logging in."
        salt = os.urandom(16).hex()
        users[email] = {
            "name": name.strip(), "role": role, "salt": salt,
            "hash": _hash_password(password, salt),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "failed": 0, "locked_until": 0,
        }
        _save_users(users)
    return True, "Account created."


def authenticate(email, password):
    """Returns (user_dict or None, message)."""
    email = email.strip().lower()
    with _users_lock():
        users = _load_users()
        u = users.get(email)
        if u is None:
            _hash_password(password, "00" * 16)  # same work as a real check
            return None, "Invalid email or password."
        now = time.time()
        if u.get("locked_until", 0) > now:
            mins = int((u["locked_until"] - now) // 60) + 1
            return None, f"Too many failed attempts. Try again in about {mins} min."
        if hmac.compare_digest(_hash_password(password, u["salt"]), u["hash"]):
            u["failed"] = 0
            u["locked_until"] = 0
            _save_users(users)
            return {"email": email, "name": u["name"], "role": u["role"]}, "OK"
        u["failed"] = u.get("failed", 0) + 1
        if u["failed"] >= MAX_FAILED_LOGINS:
            u["locked_until"] = now + LOCKOUT_SECONDS
            u["failed"] = 0
        _save_users(users)
        return None, "Invalid email or password."


def change_password(email, old_pw, new_pw):
    user, _ = authenticate(email, old_pw)
    if user is None:
        return False, "Current password is incorrect."
    problems = password_problems(new_pw)
    if problems:
        return False, "New password needs " + ", ".join(problems) + "."
    with _users_lock():
        users = _load_users()
        salt = os.urandom(16).hex()
        users[email]["salt"] = salt
        users[email]["hash"] = _hash_password(new_pw, salt)
        _save_users(users)
    return True, "Password changed."


def ensure_demo_user():
    if SEED_DEMO_USER and DEMO_EMAIL not in _load_users():
        register_user("Demo Operator", DEMO_EMAIL, ROLES[0], DEMO_PASSWORD)


def current_user():
    return st.session_state.get("ui_user")


def is_logged_in():
    return current_user() is not None


# ===========================================================================
# STATE + NAVIGATION
# ===========================================================================
def demo_config(i, name, lat, lon):
    lib = PARAMETER_LIBRARY["Water"]
    params = DEFAULT_PARAMS["Water"]
    age_months = DEMO_SENSOR_AGE_MONTHS[(i - 1) % len(DEMO_SENSOR_AGE_MONTHS)]
    installed = date.today() - timedelta(days=int(age_months * 30.44))
    return {
        "origin": "Pre-recorded (simulated)",
        "site_name": name,
        "sensor_id": f"WQ-{i:03d}",
        "domain": "Water",
        "site_type": DEMO_SITE_TYPES[(i - 1) % len(DEMO_SITE_TYPES)],
        "latitude": lat,
        "longitude": lon,
        "sensor_latitude": round(lat + 0.0015 * ((i % 3) - 1), 5),
        "sensor_longitude": round(lon + 0.0015 * (((i + 1) % 3) - 1), 5),
        "parameters": list(params),
        "ranges": {p: (lib[p]["vmin"], lib[p]["vmax"], lib[p]["typical"]) for p in params},
        **DEFAULT_CRITERIA,
        "installed": installed.isoformat(),
        "contact": "",
        "notes": "",
    }


def init_state():
    ss = st.session_state
    if not ss.get("initialised"):
        sites, readings, queue = load_demo_data()
        ss.sites = sites.copy()
        ss.readings = readings.copy()
        ss.queue = queue.copy()
        ss.configs = {
            row.site: demo_config(i, row.site, row.lat, row.lon)
            for i, row in enumerate(sites.itertuples(), start=1)
        }
        ss.page = "welcome"          # welcome | auth | dashboard | add_site
        ss.current_site = None
        ss.flash = None
        ss.ui_user = None
        ss.ui_next = None            # (page, site) to open after login
        ss.ui_ack = set()            # incident sites the user acknowledged
        ss.ui_toasted = set()
        ss.ui_rng = np.random.default_rng(7)
        ss.ui_last_tick = 0.0
        ss.ui_tick = 0
        ss.ui_anom_off = {}          # (site, parameter) -> persistent offset during an anomaly
        ss.ui_fault_log = []         # record of sensor events
        ss.ui_persist_keys = set()
        ensure_demo_user()
        ss.initialised = True
    for k, v in WIDGET_DEFAULTS.items():
        ss.setdefault(k, v)


def go(page):
    st.session_state.page = page


def request_page(page, site=None):
    """Go to a protected page; send the user to log in first if needed."""
    ss = st.session_state
    if site:
        ss.current_site = site
    if is_logged_in():
        ss.page = page
    else:
        ss.ui_next = (page, ss.current_site)
        ss.ui_auth_mode = "Log in"
        ss.page = "auth"


def open_site_from_welcome():
    choice = st.session_state.get("welcome_choice")
    if choice:
        request_page("dashboard", choice)


def open_auth(mode):
    ss = st.session_state
    ss.ui_auth_mode = mode
    ss.page = "auth"


def finish_login(user):
    ss = st.session_state
    ss.ui_user = user
    dest = ss.ui_next
    ss.ui_next = None
    if dest:
        page, site = dest
        if site:
            ss.current_site = site
        ss.page = page
    else:
        ss.page = "welcome"
    ss.flash = f"Welcome, {user['name']}!"


def logout():
    ss = st.session_state
    ss.ui_user = None
    ss.ui_next = None
    ss.current_site = None
    ss.page = "welcome"
    ss.flash = "You have been logged out."


# ===========================================================================
# DATA HELPERS
# ===========================================================================
def _stretch(fn):
    """Full-width kwarg that works on both old and new Streamlit."""
    try:
        if "width" in inspect.signature(fn).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


def show_plot(fig, key=None):
    """Plotly chart at full width."""
    st.plotly_chart(fig, key=key, **_stretch(st.plotly_chart))


def show_table(df):
    """Read-only table at full width (accepts a DataFrame or a Styler)."""
    st.dataframe(df, hide_index=True, **_stretch(st.dataframe))


def noise_ref(cfg, p):
    """Typical sensor wobble for a parameter (simulation + z-score scale)."""
    n = PARAMETER_LIBRARY.get(cfg["domain"], {}).get(p, {}).get("noise")
    if n:
        return float(n)
    typical = cfg["ranges"][p][2]
    return max(abs(typical) * 0.03, 1e-6)


def unit_of(cfg, p):
    return PARAMETER_LIBRARY.get(cfg["domain"], {}).get(p, {}).get("unit", "")


def level_z(value, typical, noise):
    """How many 'normal wobbles' a reading is from the site's normal level.
    (Swap for the pipeline's own z-score column if you prefer.)"""
    if noise <= 0 or not np.isfinite(value):
        return float("nan")
    return float((value - typical) / noise)


def threat_band(z, cfg):
    a = abs(z)
    if a >= cfg["override_z"]:
        return "Critical"
    if a >= cfg["flag_z"]:
        return "Flagged"
    if a >= 0.6 * cfg["flag_z"]:
        return "Watch"
    return "Normal"


def fault_mask(vals, vmin, vmax, noise):
    """True where a reading looks like an INSTRUMENT problem:
    missing, out of valid range, part of a stuck run, or a spike that snaps back."""
    v = np.asarray(vals, dtype=float)
    n = len(v)
    mask = np.zeros(n, dtype=bool)
    if n == 0:
        return mask
    nan = np.isnan(v)
    mask |= nan
    with np.errstate(invalid="ignore"):
        mask |= (v < vmin) | (v > vmax)
    i = 0
    while i < n:                       # stuck runs
        if nan[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and v[j + 1] == v[i]:
            j += 1
        if j - i + 1 >= STUCK_RUN:
            mask[i:j + 1] = True
        i = j + 1
    if noise and noise > 0:            # spike-reversal
        for k in range(1, n - 1):
            if nan[k] or nan[k - 1]:
                continue
            jump = abs(v[k] - v[k - 1])
            if jump < SPIKE_JUMP_SIGMA * noise:
                continue
            for back in (1, 2):
                if k + back < n and not nan[k + back] and abs(v[k + back] - v[k - 1]) <= 3 * noise:
                    mask[k] = True
                    break
    return mask


def trailing_run(mask):
    c = 0
    for x in mask[::-1]:
        if x:
            c += 1
        else:
            break
    return c


def longest_run(mask):
    best = cur = 0
    for x in mask:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def build_series(readings, site=None):
    """{(site, parameter): (timestamps array, values array)}"""
    df = readings if site is None else readings[readings["site"] == site]
    out = {}
    for key, g in df.groupby(["site", "parameter"], sort=False):
        out[key] = (g["timestamp"].to_numpy(), g["value"].to_numpy(dtype=float))
    return out


def level_info(site, p, series_map, cfg):
    ts, v = series_map.get((site, p), (None, np.array([])))
    if len(v) == 0 or p not in cfg["ranges"]:
        return None
    lo, hi, typical = cfg["ranges"][p]
    noise = noise_ref(cfg, p)
    z = level_z(v[-1], typical, noise)
    fault = bool(fault_mask(v, lo, hi, noise)[-1])
    band = "Sensor fault" if (fault or not np.isfinite(z)) else threat_band(z, cfg)
    return {"param": p, "value": float(v[-1]), "unit": unit_of(cfg, p), "z": z, "band": band,
            "typical": typical, "noise": noise, "fault": band == "Sensor fault"}


def sensor_age_months(cfg):
    try:
        d = date.fromisoformat(cfg.get("installed", ""))
    except (TypeError, ValueError):
        return None
    return max(0.0, (date.today() - d).days / 30.44)


# ---------------------------------------------------------------------------
# Simulated live feed
# ---------------------------------------------------------------------------
def live_tick():
    """Append one new simulated reading to every sensor channel."""
    ss = st.session_state
    readings = ss.readings
    configs = ss.configs
    rng = ss.ui_rng
    new_ts = readings["timestamp"].max() + pd.Timedelta(minutes=5)
    tails = readings.groupby(["site", "parameter"], sort=False).tail(40)
    rows = []
    for (site, p), g in tails.groupby(["site", "parameter"], sort=False):
        cfg = configs.get(site)
        if cfg is None or p not in cfg["ranges"]:
            continue
        lo, hi, typical = cfg["ranges"][p]
        noise = noise_ref(cfg, p)
        v = g["value"].to_numpy(dtype=float)
        key = (site, p)
        # An anomaly only "latches" after 3 flagged readings in a row,
        # so one random blip on a healthy channel does not get stuck forever.
        last_flagged = len(g) >= 3 and bool(g["flagged"].iloc[-3:].all())
        if len(v) >= STUCK_RUN and np.all(v[-STUCK_RUN:] == v[-1]):
            nxt = v[-1]                                   # stuck sensor stays stuck
        elif last_flagged:                                # keep an anomaly going
            if key not in ss.ui_anom_off:
                ss.ui_anom_off[key] = float(np.nanmean(v[-3:]) - typical)
            nxt = typical + ss.ui_anom_off[key] + rng.normal(0, 0.8 * noise)
        else:
            ss.ui_anom_off.pop(key, None)
            nxt = typical + 0.6 * (v[-1] - typical) + rng.normal(0, 0.8 * noise)
        nxt = float(np.clip(nxt, lo, hi))
        flagged = abs(level_z(nxt, typical, noise)) >= cfg["flag_z"]
        rows.append((new_ts, site, p, nxt, bool(flagged)))
    if rows:
        new = pd.DataFrame(rows, columns=["timestamp", "site", "parameter", "value", "flagged"])
        readings = pd.concat([readings, new], ignore_index=True)
        n_series = readings.groupby(["site", "parameter"], sort=False).ngroups
        if len(readings) > MAX_POINTS_PER_SERIES * n_series * 1.1:
            readings = readings.groupby(["site", "parameter"], sort=False).tail(
                MAX_POINTS_PER_SERIES).reset_index(drop=True)
        ss.readings = readings
    ss.ui_tick += 1


def maybe_tick():
    """Advance the feed if live mode is on and the interval has passed.
    Several fragments call this; only the first one in an interval actually ticks."""
    ss = st.session_state
    if not ss.ui_live_on:
        return
    now = time.time()
    if now - ss.ui_last_tick < 0.85 * float(ss.ui_live_interval):
        return
    ss.ui_last_tick = now
    live_tick()


def live_fragment(fn):
    """Wrap fn so it re-runs by itself every N seconds (N chosen by the user)."""
    ss = st.session_state
    frag = getattr(st, "fragment", None)
    if frag is None:
        return fn
    run_every = float(ss.ui_live_interval) if ss.ui_live_on else None
    return frag(run_every=run_every)(fn)


# ---------------------------------------------------------------------------
# Sensor registry
# ---------------------------------------------------------------------------
def compute_registry(series_map, configs):
    rows = []
    for site, cfg in configs.items():
        age = sensor_age_months(cfg)
        life = cfg.get("rated_life_months", 36)
        for p in cfg["parameters"]:
            ts, v = series_map.get((site, p), (np.array([], dtype="datetime64[ns]"), np.array([])))
            lo, hi, typical = cfg["ranges"][p]
            noise = noise_ref(cfg, p)
            mask = fault_mask(v, lo, hi, noise)
            n = len(v)
            share = float(mask.mean()) if n else 0.0
            cur = trailing_run(mask)
            longest = longest_run(mask)
            last_fault = pd.Timestamp(ts[mask][-1]) if mask.any() else None
            persistent = cur >= PERSIST_RUN or (n >= 24 and share >= 0.25)
            worn = age is not None and age >= life
            intermittent = bool(mask.any()) and not persistent
            parts = []
            if persistent:
                parts.append("Persistently faulty")
            if worn:
                parts.append("Worn out")
            if not parts:
                parts.append("Intermittent faults" if intermittent else "Healthy")
            if persistent:
                action = "Inspect / clean / replace probe"
            elif worn:
                action = "Schedule replacement"
            elif intermittent:
                action = "Monitor"
            else:
                action = "-"
            rows.append({
                "sensor_id": cfg["sensor_id"], "site": site, "parameter": p,
                "status": " + ".join(parts),
                "age_months": age, "rated_life_months": life,
                "fault_share": share, "current_run": cur, "longest_run": longest,
                "last_fault": last_fault, "action": action,
                "persistent": persistent, "worn": worn, "intermittent": intermittent,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        order = df["persistent"].astype(int) * 4 + df["worn"].astype(int) * 2 + df["intermittent"].astype(int)
        df = df.assign(_o=order).sort_values(["_o", "site"], ascending=[False, True]).drop(columns="_o")
        df = df.reset_index(drop=True)
    return df


def update_fault_log(reg):
    """Keep a running record of when sensors became / stopped being persistently faulty."""
    ss = st.session_state
    now = ss.readings["timestamp"].max()
    stamp = pd.Timestamp(now).strftime("%d %b %H:%M")
    ids = {(r.site, r.parameter): r.sensor_id for r in reg.itertuples()}
    cur = {(r.site, r.parameter) for r in reg.itertuples() if r.persistent}
    prev = ss.ui_persist_keys
    for key in sorted(cur - prev):
        ss.ui_fault_log.append({"time": stamp, "sensor": ids.get(key, "?"), "site": key[0],
                                "parameter": key[1], "event": "Became persistently faulty"})
    for key in sorted(prev - cur):
        ss.ui_fault_log.append({"time": stamp, "sensor": ids.get(key, "?"), "site": key[0],
                                "parameter": key[1], "event": "Recovered"})
    ss.ui_persist_keys = cur


def registry_display(reg):
    out = pd.DataFrame({
        "Sensor": reg["sensor_id"], "Site": reg["site"], "Parameter": reg["parameter"],
        "Status": reg["status"],
        "Age (months)": reg["age_months"].map(lambda x: "-" if pd.isna(x) else f"{x:.0f}"),
        "Rated life": reg["rated_life_months"].astype(str),
        "Fault share": reg["fault_share"].map(lambda x: f"{x * 100:.0f}%"),
        "Fault run now": reg["current_run"].astype(int),
        "Last fault": reg["last_fault"].map(lambda t: "-" if t is None or pd.isna(t) else t.strftime("%d %b %H:%M")),
        "Action": reg["action"],
    })
    return out


def style_status(df):
    def colour(v):
        if "Persistently" in v:
            return f"color:{T['red']};font-weight:600"
        if "Worn" in v:
            return f"color:{T['orange']};font-weight:600"
        if "Intermittent" in v:
            return f"color:{T['yellow']}"
        return f"color:{T['green']}"
    try:
        return df.style.map(colour, subset=["Status"])
    except Exception:
        try:
            return df.style.applymap(colour, subset=["Status"])
        except Exception:
            return df


# ---------------------------------------------------------------------------
# HTML builders (single-line strings: no indentation, so Markdown never treats them as code)
# ---------------------------------------------------------------------------
def fmt_value(x):
    return "–" if not np.isfinite(x) else f"{x:,.2f}"


def levels_html(infos, cfg):
    scale = cfg["override_z"] * 1.25
    flag_pos = min(100.0, cfg["flag_z"] / scale * 100)
    crit_pos = min(100.0, cfg["override_z"] / scale * 100)
    rows = []
    for i in infos:
        color = BAND_COLORS[i["band"]]
        if i["fault"]:
            width = 100.0
            note = "Sensor fault suspected: reading not trusted"
        else:
            width = max(4.0, min(100.0, abs(i["z"]) / scale * 100))
            note = f"{i['band']} · {i['z']:+.1f}σ from normal"
        striped = " vf-striped" if i["fault"] else ""
        rows.append(
            "<div class='vf-lvl'>"
            f"<div class='vf-lvl-head'><span>{html.escape(i['param'])}</span>"
            f"<b>{fmt_value(i['value'])} {html.escape(i['unit'])}</b></div>"
            "<div class='vf-lvl-track'>"
            f"<div class='vf-lvl-fill{striped}' style='width:{width:.1f}%;background-color:{color}'></div>"
            f"<span class='vf-tick' style='left:{flag_pos:.1f}%'></span>"
            f"<span class='vf-tick vf-tick-crit' style='left:{crit_pos:.1f}%'></span>"
            "</div>"
            f"<div class='vf-lvl-note' style='color:{color}'>{html.escape(note)}</div>"
            "</div>")
    return f"<div class='vf-lvls'>{''.join(rows)}</div>"


def tank_pct(value, typical, noise):
    if not np.isfinite(value) or noise <= 0:
        return 6.0
    frac = float(np.clip((value - typical) / (8 * noise), -1, 1))
    return max(3.0, 50 + 50 * frac)


def tank_html(info, mini=False):
    color = BAND_COLORS[info["band"]]
    pct = tank_pct(info["value"], info["typical"], info["noise"])
    still = " vf-still" if info["fault"] else ""
    size = " mini" if mini else ""
    sub = "Sensor fault" if info["fault"] else f"{info['band']} · {info['z']:+.1f}σ"
    return (
        "<div class='vf-tank-wrap'>"
        f"<div class='vf-tank{size}{still}' style='--c:{color}'>"
        f"<div class='vf-water' style='height:{pct:.0f}%'><div class='vf-wave'></div></div>"
        f"<div class='vf-tank-val'>{fmt_value(info['value'])}</div></div>"
        f"<div class='vf-tank-label'>{html.escape(info['param'])}</div>"
        f"<div class='vf-tank-sub'>{html.escape(info['unit'])}</div>"
        f"<div class='vf-tank-sub' style='color:{color}'>{html.escape(sub)}</div>"
        "</div>")


def config_rows(cfg):
    """Settings shown on the dashboard. Add new fields here as the form grows."""
    return [
        ("Sensor number / ID", cfg["sensor_id"]),
        ("Monitoring domain", cfg["domain"]),
        ("Type of site", cfg["site_type"]),
        ("Site location (lat, lon)", f"{cfg['latitude']:.5f}, {cfg['longitude']:.5f}"),
        ("Sensor location (lat, lon)", f"{cfg.get('sensor_latitude', cfg['latitude']):.5f}, "
                                       f"{cfg.get('sensor_longitude', cfg['longitude']):.5f}"),
        ("Parameters tracked", ", ".join(cfg["parameters"])),
        ("Sensor installed on", cfg.get("installed", "-")),
        ("Rated sensor life", f"{cfg.get('rated_life_months', '-')} months"),
        ("Flag event level (|z| ≥)", f"{cfg['flag_z']}"),
        ("Consecutive flags for Potential Incident", f"{cfg['persistence']}"),
        ("Strong-deviation level (|z| ≥)", f"{cfg['override_z']}"),
        ("Sensor unreliable if R <", f"{cfg['r_unreliable']}"),
        ("Incident needs R ≥", f"{cfg['r_incident']}"),
        ("Complaints → Needs Verification", f"{cfg['complaints_verify']}+"),
        ("Complaints counted as support", f"{cfg['complaints_support']}+"),
        ("Sampling interval", f"{cfg['sampling_minutes']} min"),
        ("Location sensitivity (0-1)", f"{cfg['location_sensitivity']}"),
        ("Responsible contact", cfg["contact"] or "-"),
        ("Notes", cfg["notes"] or "-"),
    ]


# ---------------------------------------------------------------------------
# Add-site helpers
# ---------------------------------------------------------------------------
def simulate_baseline(site, domain, ranges, times):
    """Normal-behaviour readings for a newly added site (no live feed yet)."""
    rng = np.random.default_rng(zlib.crc32(site.encode("utf-8")))
    lib = PARAMETER_LIBRARY[domain]
    rows = []
    for p, (lo, hi, typical) in ranges.items():
        vals = typical + rng.normal(0, lib[p]["noise"], len(times))
        vals = np.clip(vals, lo, hi)
        for t, v in zip(times, vals):
            rows.append((t, site, p, float(v), False))
    return pd.DataFrame(rows, columns=["timestamp", "site", "parameter", "value", "flagged"])


def save_new_site(cfg):
    ss = st.session_state
    name = cfg["site_name"]
    times = ss.readings["timestamp"].drop_duplicates().sort_values().tolist()
    new_readings = simulate_baseline(name, cfg["domain"], cfg["ranges"], times)
    ss.readings = pd.concat([ss.readings, new_readings], ignore_index=True)
    new_row = pd.DataFrame([{"site": name, "lat": cfg["latitude"], "lon": cfg["longitude"],
                             "status": "Normal", "score": 0}])
    ss.sites = pd.concat([ss.sites, new_row], ignore_index=True)
    ss.configs[name] = cfg
    ss.current_site = name
    ss.page = "dashboard"
    ss.flash = (f"'{name}' added. Showing simulated baseline readings "
                "until a real sensor feed is connected.")


def validate_new_site(cfg, range_errors):
    errors = list(range_errors)
    existing_names = {n.lower() for n in st.session_state.configs}
    existing_sensors = {c["sensor_id"].lower() for c in st.session_state.configs.values()}
    if not cfg["site_name"]:
        errors.append("Site name is required.")
    elif cfg["site_name"].lower() in existing_names:
        errors.append(f"A site named '{cfg['site_name']}' already exists.")
    if not cfg["sensor_id"]:
        errors.append("Sensor number / ID is required.")
    elif cfg["sensor_id"].lower() in existing_sensors:
        errors.append(f"Sensor '{cfg['sensor_id']}' is already registered.")
    if not cfg["parameters"]:
        errors.append("Choose at least one parameter to track.")
    if cfg["override_z"] < cfg["flag_z"]:
        errors.append("Strong-deviation level must be at least the flag event level.")
    if cfg["r_incident"] < cfg["r_unreliable"]:
        errors.append("Reliability needed for an incident must be at least the 'unreliable' level.")
    if cfg.get("installed", "") > date.today().isoformat():
        errors.append("Sensor install date cannot be in the future.")
    return errors


# ===========================================================================
# SHARED UI PIECES
# ===========================================================================
def show_flash():
    ss = st.session_state
    if ss.flash:
        st.toast(ss.flash, icon="✅")
        ss.flash = None


def ack_alert(site):
    st.session_state.ui_ack = st.session_state.ui_ack | {site}


def open_alert_site(site):
    ack_alert(site)
    st.session_state.current_site = site
    st.session_state.page = "dashboard"


def incident_sites():
    s = st.session_state.sites
    return s[(s["status"] == "Potential Incident") & (s["score"] >= ALERT_MIN_SCORE)]


def render_alert_popups():
    """Side pop-up for genuine threats: evidence-backed Potential Incident with a high score.
    (One high reading never triggers it; that is the whole point of VeriFlow.)"""
    ss = st.session_state
    if not is_logged_in():
        return
    inc = incident_sites()
    names = set(inc["site"])
    ss.ui_ack = ss.ui_ack & names            # a cleared incident can alert again later
    ss.ui_toasted = ss.ui_toasted & names
    pending = inc[~inc["site"].isin(ss.ui_ack)]
    if pending.empty:
        return
    for s in pending["site"]:
        if s not in ss.ui_toasted:
            st.toast(f"{s}: potential incident, immediate attention needed", icon="🚨")
            ss.ui_toasted = ss.ui_toasted | {s}
    try:
        box = st.container(key="vf_alert_panel")
    except TypeError:                         # very old Streamlit: show inline instead
        box = st.container()
    with box:
        st.markdown("### 🚨 Immediate attention")
        for row in pending.itertuples():
            st.markdown(f"**{row.site}** · Potential Incident · Evidence Score **{row.score}**")
            for line in DETAILS.get(row.site, {}).get("why", [])[:2]:
                st.caption("• " + line)
            b1, b2 = st.columns(2)
            b1.button("Open site", key=f"vf_open_{row.site}", on_click=open_alert_site, args=(row.site,))
            b2.button("Acknowledge", key=f"vf_ack_{row.site}", on_click=ack_alert, args=(row.site,))
        st.caption("Rule-based evidence, not proof of contamination. "
                   "Needs human review and confirmatory testing.")


def render_user_sidebar():
    user = current_user()
    if not user:
        return
    sb = st.sidebar
    sb.markdown(f"👤 **{user['name']}**")
    sb.caption(user["role"])
    sb.button("Log out", on_click=logout, key="vf_logout_sidebar")
    with sb.expander("Change password"):
        with st.form("vf_pw_form", clear_on_submit=True):
            old = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password")
            new2 = st.text_input("Repeat new password", type="password")
            done = st.form_submit_button("Update password")
        if done:
            if new != new2:
                st.error("New passwords do not match.")
            else:
                ok, msg = change_password(user["email"], old, new)
                (st.success if ok else st.error)(msg)
    sb.divider()


# ===========================================================================
# PAGE: Welcome
# ===========================================================================
def page_welcome():
    # Top-right: Log in / Sign up, or the signed-in user
    _, right = st.columns([5, 2])
    with right:
        user = current_user()
        if user:
            u1, u2 = st.columns([3, 2], vertical_alignment="center")
            u1.markdown(f"<div class='vf-user'>👤 <b>{html.escape(user['name'])}</b><br>"
                        f"<small>{html.escape(user['role'])}</small></div>", unsafe_allow_html=True)
            u2.button("Log out", on_click=logout, key="vf_logout_top")
        else:
            a1, a2 = st.columns(2)
            a1.button("Log in", on_click=open_auth, args=("Log in",), key="vf_login_top")
            a2.button("Sign up", on_click=open_auth, args=("Sign up",), type="primary",
                      key="vf_signup_top")

    st.markdown(
        "<div class='vf-hero'><h1>🏮 VeriFlow</h1><p>Evidence before alarm.</p></div>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        st.markdown("##### Choose a monitoring site")
        left, right = st.columns([3, 2], vertical_alignment="bottom")
        with left:
            st.selectbox(
                "Select a pre-recorded site",
                options=st.session_state.sites["site"].tolist(),
                index=None,
                placeholder="Choose a site...",
                key="welcome_choice",
                on_change=open_site_from_welcome,
            )
        with right:
            st.button("➕  Add new site / sensor", on_click=request_page, args=("add_site",))
        if is_logged_in():
            st.caption("Pick an existing site to see its dashboard, or register a new site and sensor.")
        else:
            st.caption("Log in or sign up (top right) to open a site dashboard or add a new site.")

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.caption("Simulated-data prototype. Suspected incidents need human review "
               "and confirmatory testing.")


# ===========================================================================
# PAGE: Auth (log in / sign up)
# ===========================================================================
def _login_form():
    with st.form("vf_login_form"):
        email = st.text_input("Email", key="ui_login_email")
        password = st.text_input("Password", type="password", key="ui_login_pw")
        submitted = st.form_submit_button("Log in", type="primary")
    if SEED_DEMO_USER:
        st.caption(f"Demo account: {DEMO_EMAIL}  /  {DEMO_PASSWORD}")
    if submitted:
        if not email.strip() or not password:
            st.error("Enter your email and password.")
            return
        user, msg = authenticate(email, password)
        if user:
            finish_login(user)
            st.rerun()
        else:
            st.error(msg)


def _signup_form():
    with st.form("vf_signup_form"):
        name = st.text_input("Full name", key="ui_su_name")
        email = st.text_input("Email", key="ui_su_email")
        role = st.selectbox("Your role", ROLES, key="ui_su_role")
        pw = st.text_input("Password", type="password", key="ui_su_pw")
        pw2 = st.text_input("Confirm password", type="password", key="ui_su_pw2")
        submitted = st.form_submit_button("Create account", type="primary")
    st.caption("Password: at least 8 characters, with a letter and a number.")
    if submitted:
        errors = []
        if not name.strip():
            errors.append("Enter your name.")
        if not EMAIL_RE.match(email.strip()):
            errors.append("Enter a valid email address.")
        problems = password_problems(pw)
        if problems:
            errors.append("Password needs " + ", ".join(problems) + ".")
        if pw != pw2:
            errors.append("Passwords do not match.")
        if errors:
            for e in errors:
                st.error(e)
            return
        ok, msg = register_user(name, email, role, pw)
        if not ok:
            st.error(msg)
            return
        user, _ = authenticate(email, pw)
        if user:
            finish_login(user)
            st.rerun()


def page_auth():
    st.button("← Back to home", on_click=go, args=("welcome",))
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("<div class='vf-auth-title'><h1>🏮 VeriFlow</h1>"
                    "<p>Evidence before alarm.</p></div>", unsafe_allow_html=True)
        if st.session_state.ui_next:
            st.info("Please log in or create an account to continue.")
        mode = st.radio("Account", ["Log in", "Sign up"], horizontal=True,
                        key="ui_auth_mode", label_visibility="collapsed")
        if mode == "Log in":
            _login_form()
        else:
            _signup_form()
        st.caption("Prototype sign-in: accounts are stored on this machine with salted, hashed "
                   "passwords. Not for production use.")


# ===========================================================================
# PAGE: Add new site / sensor
# ===========================================================================
def page_add_site():
    render_user_sidebar()
    st.button("← Back to home", on_click=go, args=("welcome",))
    st.markdown("## ➕ Add a new site / sensor")
    st.caption("Fields marked * are required. Settings are kept for this session "
               "(prototype: no database).")

    # ---- 1. Site and sensor -------------------------------------------------
    st.subheader("1. Site and sensor")
    c1, c2 = st.columns(2)
    site_name = c1.text_input("Site name *", key="new_name",
                              placeholder="e.g. Hostel Block B tank").strip()
    sensor_id = c2.text_input("Sensor number / ID *", key="new_sensor",
                              placeholder="e.g. WQ-009").strip()
    domain = c1.selectbox("Monitoring domain", ["Water", "Air"], key="new_domain")
    site_type = c2.selectbox("Type of site", SITE_TYPES[domain], key=f"new_type_{domain}")
    installed = c1.date_input("Sensor installed on", value=date.today(), max_value=date.today(),
                              key="new_installed")
    rated_life = c2.number_input("Rated sensor life (months)", 6, 240,
                                 DEFAULT_CRITERIA["rated_life_months"], key="new_life",
                                 help="Used to flag worn-out sensors in the sensor registry.")

    # ---- 2. Location (map) ---------------------------------------------------
    st.subheader("2. Location: site and sensor")
    loc = maps.location_picker(st.session_state.sites)
    latitude, longitude = loc["site"]
    sensor_lat, sensor_lon = loc["sensor"]

    # ---- 3. Fields to track -------------------------------------------------
    st.subheader("3. Fields to track")
    lib = PARAMETER_LIBRARY[domain]
    parameters = st.multiselect("Parameters measured by this sensor *", list(lib),
                                default=DEFAULT_PARAMS[domain], key=f"new_params_{domain}")

    ranges = {}
    range_errors = []
    if parameters:
        table = pd.DataFrame([{
            "Parameter": p, "Unit": lib[p]["unit"],
            "Valid min": lib[p]["vmin"], "Valid max": lib[p]["vmax"],
            "Typical value": lib[p]["typical"],
        } for p in parameters])
        edited = st.data_editor(
            table, hide_index=True, disabled=["Parameter", "Unit"],
            key=f"new_ranges_{domain}_{'|'.join(parameters)}",
        )
        st.caption("Valid range: readings outside it count as out-of-range in the sensor "
                   "reliability score R. Typical value: starting level for the simulated baseline.")
        for _, r in edited.iterrows():
            p = r["Parameter"]
            lo, hi, typ = r["Valid min"], r["Valid max"], r["Typical value"]
            if pd.isna(lo) or pd.isna(hi) or pd.isna(typ):
                range_errors.append(f"{p}: fill in min, max and typical value.")
            elif lo >= hi:
                range_errors.append(f"{p}: valid min must be below valid max.")
            elif not lo <= typ <= hi:
                range_errors.append(f"{p}: typical value must lie within the valid range.")
            else:
                ranges[p] = (float(lo), float(hi), float(typ))

    # ---- 3. Flag level and warning criteria ----------------------------------
    st.subheader("4. Flag event level and warning criteria")
    d = DEFAULT_CRITERIA
    a, b = st.columns(2)
    with a:
        st.markdown("**Flagging**")
        flag_z = st.slider("Flag event level (|z| ≥)", 2.0, 6.0, d["flag_z"], 0.1, key="new_flag_z",
                           help="A reading is flagged when its modified z-score is at least this.")
        persistence = st.slider("Consecutive flags for Potential Incident", 1, 6,
                                d["persistence"], key="new_persistence",
                                help="One reading never confirms unsafe water; persistence is required.")
        override_z = st.slider("Strong-deviation level (|z| ≥)", 3.0, 10.0, d["override_z"], 0.5,
                               key="new_override_z",
                               help="Deviations this large can escalate even without extra support.")
        sampling_minutes = st.selectbox("Sampling interval (minutes)", SAMPLING_OPTIONS,
                                        index=SAMPLING_OPTIONS.index(d["sampling_minutes"]),
                                        key="new_sampling")
    with b:
        st.markdown("**Warning criteria**")
        r_unreliable = st.slider("Sensor unreliable if R <", 0.1, 0.9, d["r_unreliable"], 0.05,
                                 key="new_r_unrel")
        r_incident = st.slider("Potential Incident needs R ≥", 0.3, 0.95, d["r_incident"], 0.05,
                               key="new_r_inc")
        complaints_verify = st.number_input("Complaints (sensors normal) → Needs Verification",
                                            1, 20, d["complaints_verify"], key="new_c_verify")
        complaints_support = st.number_input("Complaints counted as support for an incident",
                                             1, 10, d["complaints_support"], key="new_c_support")
        location_sensitivity = st.slider("Location sensitivity (0 = low, 1 = high)", 0.0, 1.0,
                                         d["location_sensitivity"], 0.05, key="new_sens",
                                         help="Used to rank the queue: higher = investigated sooner.")

    # ---- 4. Contact and notes ------------------------------------------------
    st.subheader("5. Contact and notes (optional)")
    contact = st.text_input("Responsible person / team", key="new_contact")
    notes = st.text_area("Notes", key="new_notes", height=80)

    # ---- Save ----------------------------------------------------------------
    st.divider()
    s1, s2, _ = st.columns([1, 1, 4])
    save_clicked = s1.button("Save site", type="primary")
    s2.button("Cancel", on_click=go, args=("welcome",))

    if save_clicked:
        cfg = {
            "origin": "Added by user",
            "site_name": site_name, "sensor_id": sensor_id, "domain": domain,
            "site_type": site_type, "latitude": latitude, "longitude": longitude,
            "sensor_latitude": sensor_lat, "sensor_longitude": sensor_lon,
            "parameters": list(parameters), "ranges": ranges,
            "installed": installed.isoformat(), "rated_life_months": int(rated_life),
            "flag_z": flag_z, "persistence": persistence, "override_z": override_z,
            "r_unreliable": r_unreliable, "r_incident": r_incident,
            "complaints_verify": int(complaints_verify),
            "complaints_support": int(complaints_support),
            "location_sensitivity": location_sensitivity,
            "sampling_minutes": int(sampling_minutes),
            "contact": contact.strip(), "notes": notes.strip(),
        }
        errors = validate_new_site(cfg, range_errors)
        if errors:
            for e in errors:
                st.error(e)
        else:
            save_new_site(cfg)
            st.rerun()


# ===========================================================================
# PAGE: Site dashboard
# ===========================================================================
# ---- live fragments (each re-runs by itself every N seconds) ---------------
def frag_trends():
    maybe_tick()
    ss = st.session_state
    site = ss.current_site
    d = ss.readings[ss.readings["site"] == site]
    d = d.groupby("parameter", sort=False).tail(24).copy()
    if d.empty:
        st.info("No readings for this site yet.")
        return
    d["type"] = np.where(d["flagged"], "Flagged", "Baseline")
    fig = px.line(
        d, x="timestamp", y="value", color="type", facet_col="parameter",
        facet_col_wrap=2, markers=True,
        color_discrete_map={"Baseline": T["orange"], "Flagged": T["red"]},
    )
    fig.update_yaxes(matches=None, showticklabels=True)
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    fig.update_traces(line=dict(width=2.5))
    fig.update_layout(height=400, legend_title_text="", margin=dict(l=0, r=0, t=30, b=0))
    style_figure(fig)
    show_plot(fig, key="ui_trends_chart")


def frag_levels():
    maybe_tick()
    ss = st.session_state
    site = ss.current_site
    cfg = ss.configs[site]
    series_map = build_series(ss.readings, site)
    infos = [i for i in (level_info(site, p, series_map, cfg) for p in cfg["parameters"]) if i]
    if not infos:
        st.info("No readings for this site yet.")
        return
    st.markdown(levels_html(infos, cfg), unsafe_allow_html=True)
    st.markdown(
        f"<div class='vf-legend'>Bar length = distance from this site's normal level. "
        f"White tick = flag level (|z| ≥ {cfg['flag_z']}), red tick = strong deviation "
        f"(|z| ≥ {cfg['override_z']}). "
        f"{BAND_EMOJI['Normal']} normal  {BAND_EMOJI['Watch']} watch  {BAND_EMOJI['Flagged']} flagged  "
        f"{BAND_EMOJI['Critical']} critical  {BAND_EMOJI['Sensor fault']} sensor fault "
        "(reading not trusted).</div>", unsafe_allow_html=True)


def live_figure(site, cfg, params, n, series_map):
    k = len(params)
    ncols = 2 if k > 1 else 1
    nrows = math.ceil(k / ncols)
    titles = [f"{p} ({unit_of(cfg, p)})" if unit_of(cfg, p) else p for p in params]
    fig = make_subplots(rows=nrows, cols=ncols, subplot_titles=titles,
                        vertical_spacing=0.2, horizontal_spacing=0.08)
    for i, p in enumerate(params):
        r, c = i // ncols + 1, i % ncols + 1
        ts, v = series_map.get((site, p), (np.array([]), np.array([])))
        if len(v) == 0:
            continue
        lo, hi, typical = cfg["ranges"][p]
        noise = noise_ref(cfg, p)
        mask = fault_mask(v, lo, hi, noise)
        v_n, t_n, m_n = v[-n:], ts[-n:], mask[-n:]
        colors, custom = [], []
        for val, bad in zip(v_n, m_n):
            z = level_z(val, typical, noise)
            band = "Sensor fault" if (bad or not np.isfinite(z)) else threat_band(z, cfg)
            colors.append(BAND_COLORS[band])
            custom.append([z, band])
        fig.add_trace(pgo.Bar(
            x=t_n, y=v_n, marker_color=colors, customdata=custom, showlegend=False,
            hovertemplate="%{x|%H:%M}<br>%{y:.3f}<br>%{customdata[1]} · %{customdata[0]:+.1f}σ<extra></extra>",
        ), row=r, col=c)
        fig.add_hline(y=typical, line_dash="dot", line_color=T["muted"], row=r, col=c)
        for sign in (1, -1):
            fig.add_hline(y=typical + sign * cfg["flag_z"] * noise, line_dash="dash",
                          line_color=BAND_COLORS["Flagged"], line_width=1, row=r, col=c)
        lo_y = min(np.nanmin(v_n), typical - (cfg["flag_z"] + 1) * noise)
        hi_y = max(np.nanmax(v_n), typical + (cfg["flag_z"] + 1) * noise)
        pad = 0.08 * (hi_y - lo_y)
        fig.update_yaxes(range=[lo_y - pad, hi_y + pad], row=r, col=c)
    fig.update_layout(height=260 * nrows + 30, showlegend=False, bargap=0.15,
                      margin=dict(l=0, r=0, t=40, b=0))
    return style_figure(fig)


def frag_live_graph():
    maybe_tick()
    ss = st.session_state
    site = ss.current_site
    cfg = ss.configs[site]
    choice = ss.get(f"ui_live_param_{site}", "All parameters")
    params = cfg["parameters"] if choice == "All parameters" else [choice]
    params = [p for p in params if p in cfg["parameters"]] or cfg["parameters"]
    series_map = build_series(ss.readings, site)
    if not series_map:
        st.info("No readings for this site yet.")
        return
    fig = live_figure(site, cfg, params, int(ss.ui_live_points), series_map)
    show_plot(fig, key="ui_live_chart")
    latest = pd.Timestamp(ss.readings["timestamp"].max()).strftime("%H:%M")
    state = f"● LIVE every {ss.ui_live_interval} s" if ss.ui_live_on else "⏸ Paused"
    st.caption(f"{state} · update #{ss.ui_tick} · latest reading {latest} (simulated clock) · "
               f"dotted line = normal level, dashed orange = flag level. "
               f"Colours: {BAND_EMOJI['Normal']} normal  {BAND_EMOJI['Watch']} watch  "
               f"{BAND_EMOJI['Flagged']} flagged  {BAND_EMOJI['Critical']} critical  "
               f"{BAND_EMOJI['Sensor fault']} sensor fault")


def frag_registry():
    maybe_tick()
    ss = st.session_state
    reg = compute_registry(build_series(ss.readings), ss.configs)
    if reg.empty:
        st.info("No sensors registered.")
        return
    update_fault_log(reg)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Persistently faulty channels", int(reg["persistent"].sum()))
    m2.metric("Worn-out sensors", int(reg.loc[reg["worn"], "sensor_id"].nunique()))
    m3.metric("Intermittent faults", int(reg["intermittent"].sum()))
    m4.metric("Healthy channels", int((reg["status"] == "Healthy").sum()))

    options = ["All", "Persistently faulty", "Worn out", "Intermittent", "Healthy"]
    pick = st.selectbox("Show", options, key="ui_reg_filter")
    view = reg if pick == "All" else reg[reg["status"].str.contains(pick, regex=False)]
    if view.empty:
        st.info("No sensors in this category.")
    else:
        show_table(style_status(registry_display(view)))
    st.caption(f"Persistently faulty = fault lasting {PERSIST_RUN}+ readings (stuck, missing, "
               f"out-of-range) or faulty in 25%+ of the last 24 h. Worn out = sensor age at or past "
               f"its rated life. Intermittent = isolated faults that cleared.")

    d1, d2 = st.columns(2)
    d1.download_button("⬇ Download sensor record (CSV)",
                       registry_display(reg).to_csv(index=False).encode("utf-8"),
                       file_name="veriflow_sensor_record.csv", mime="text/csv",
                       key="ui_dl_registry")
    with st.expander(f"Sensor event log ({len(ss.ui_fault_log)})"):
        if ss.ui_fault_log:
            log = pd.DataFrame(ss.ui_fault_log).iloc[::-1].reset_index(drop=True)
            log.columns = ["Time", "Sensor", "Site", "Parameter", "Event"]
            show_table(log)
            d2.download_button("⬇ Download event log (CSV)", log.to_csv(index=False).encode("utf-8"),
                               file_name="veriflow_sensor_events.csv", mime="text/csv",
                               key="ui_dl_events")
        else:
            st.write("No events recorded yet.")


def frag_tanks():
    maybe_tick()
    ss = st.session_state
    scope = st.radio("Show tanks for", ["This site", "All sites"], horizontal=True,
                     key="ui_tank_scope")
    if scope == "This site":
        sites_to_show = [ss.current_site]
    else:
        sites_to_show = list(ss.configs)
    series_map = build_series(ss.readings)
    parts = []
    for site in sites_to_show:
        cfg = ss.configs[site]
        infos = [i for i in (level_info(site, p, series_map, cfg) for p in cfg["parameters"]) if i]
        if not infos:
            continue
        mini = scope == "All sites"
        head = f"<div class='vf-tank-site'>{html.escape(site)}</div>" if mini else ""
        parts.append(head + "<div class='vf-tanks'>" + "".join(tank_html(i, mini) for i in infos) + "</div>")
    if parts:
        st.markdown("".join(parts), unsafe_allow_html=True)
        st.caption("Tank level: middle = this sensor's normal level, fuller = reading above normal, "
                   "emptier = below normal. Colour shows the threat band; grey = sensor fault.")
    else:
        st.info("No readings yet.")


def page_dashboard():
    ss = st.session_state
    sites = ss.sites
    queue = ss.queue
    names = sites["site"].tolist()
    chosen_site = ss.current_site
    cfg = ss.configs[chosen_site]

    # Sidebar: user, navigation, site switcher
    render_user_sidebar()
    st.sidebar.button("← Home", on_click=go, args=("welcome",))
    picked = st.sidebar.selectbox("Location", names, index=names.index(chosen_site))
    if picked != chosen_site:
        ss.current_site = picked
        ss.ui_map_last_tip = None
        st.rerun()
    st.sidebar.button("➕ Add new site / sensor", on_click=go, args=("add_site",))

    # Header
    st.markdown("## 🏮 VeriFlow <span class='vf-badge'>SIMULATED DATA</span>",
                unsafe_allow_html=True)
    st.caption("Evidence before alarm. Every case needs human review and confirmatory testing.")
    st.markdown(f"**{chosen_site}**  ·  Sensor {cfg['sensor_id']}  ·  {cfg['site_type']}  ·  "
                f"{cfg['domain']}")

    # Number cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Locations", len(sites))
    c2.metric("Anomalies", int((sites["status"] != "Normal").sum()))
    c3.metric("Suspected faults", int((sites["status"] == "Sensor Fault Suspected").sum()))
    c4.metric("Need investigation", int((sites["status"] == "Potential Incident").sum()))

    # Map + live trends
    left, right = st.columns([5, 6])
    with left:
        st.subheader("Map: status pins")
        clicked = maps.status_map(sites, ss.configs, chosen_site, key="vf_status_map", height=400)
        if clicked and clicked != ss.get("ui_map_last_tip"):
            ss.ui_map_last_tip = clicked              # act on each pin click only once
            if clicked in names and clicked != chosen_site:
                ss.current_site = clicked
                st.rerun()
    with right:
        st.subheader(f"Trends: last 2 h  ({chosen_site})")
        live_fragment(frag_trends)()

    # Alert queue
    st.subheader("Alert queue")
    show_table(queue)
    st.caption("Queue: P1 Potential Incident, P2 Needs Verification; "
               "ties by Evidence Score x (0.7 + 0.3 x location sensitivity). "
               "Sample values are simulated.")

    # Alert detail (scoring)
    st.subheader(f"Alert detail: {chosen_site}")
    row = sites[sites["site"] == chosen_site].iloc[0]
    st.markdown(f"**Status:** {row['status']}  |  **Evidence Score:** {row['score']} "
                "(rule-based, not a probability)")
    info = DETAILS.get(chosen_site)
    if info:
        a, b = st.columns(2)
        with a:
            st.markdown("**Why flagged**")
            for line in info["why"]:
                st.write("•", line)
        with b:
            st.markdown("**Next actions**")
            for line in info["actions"]:
                st.write("•", line)
    else:
        st.info("No active alert for this site.")

    # ------------------------------------------------------------------
    # Everything below the scoring is LIVE
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("📡 Live monitor")
    if not hasattr(st, "fragment"):
        st.warning("Auto-refresh needs Streamlit 1.37 or newer: pip install -U streamlit")
    k1, k2, k3, k4 = st.columns(4, vertical_alignment="bottom")
    k1.toggle("Live feed", key="ui_live_on")
    k2.selectbox("Refresh every", LIVE_INTERVALS, key="ui_live_interval",
                 format_func=lambda s: f"{s} s")
    k3.slider("Bars shown", 10, 60, key="ui_live_points")
    k4.selectbox("Graph parameter", ["All parameters"] + cfg["parameters"],
                 key=f"ui_live_param_{chosen_site}")

    st.markdown("#### Reading levels")
    live_fragment(frag_levels)()

    st.markdown("#### Live graphs")
    live_fragment(frag_live_graph)()

    st.markdown("#### Sensor registry: faulty and worn-out sensors")
    live_fragment(frag_registry)()

    st.markdown("#### Live water-level view of every sensor reading")
    live_fragment(frag_tanks)()

    # Site configuration
    with st.expander("Site configuration"):
        show_table(pd.DataFrame(config_rows(cfg), columns=["Setting", "Value"]))
        rng_df = pd.DataFrame([
            {"Parameter": p, "Valid min": lo, "Valid max": hi, "Typical value": typ}
            for p, (lo, hi, typ) in cfg["ranges"].items()
        ])
        if not rng_df.empty:
            show_table(rng_df)


# ===========================================================================
# Router
# ===========================================================================
init_state()
inject_css()
page = st.session_state.page
if page in PROTECTED_PAGES and not is_logged_in():
    st.session_state.ui_next = (page, st.session_state.current_site)
    st.session_state.page = page = "auth"
if page == "dashboard" and not st.session_state.current_site:
    st.session_state.page = page = "welcome"

if page != "auth":
    show_flash()
    render_alert_popups()

if page == "auth":
    page_auth()
elif page == "add_site":
    page_add_site()
elif page == "dashboard":
    page_dashboard()
else:
    page_welcome()
