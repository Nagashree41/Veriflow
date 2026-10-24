"""
VeriFlow - multi-page Streamlit app (prototype, SIMULATED DATA)

  Page 1   Welcome        : project name, pick a pre-recorded site OR add a new one
  Page 2a  Site dashboard : number cards, map, trends, alert queue, alert detail
  Page 2b  Add new site   : sensor number, site type, parameters, flag level, warning criteria

Run:  streamlit run app.py

How to extend later
-------------------
* New form field  -> add one widget in page_add_site() and one key in the `cfg` dict there.
* New setting row -> add it to config_rows() so it shows on the dashboard too.
* Real pipeline   -> replace load_demo_data() so it returns the same 3 tables
                     (sites, readings, queue). Per-site settings live in
                     st.session_state.configs[site_name]; the detection code should read them.
"""
import zlib

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="VeriFlow", page_icon="🏮", layout="wide")

ORANGE = "#F7931E"
STATUS_COLORS = {
    "Normal": "#4CAF50",
    "Sensor Fault Suspected": "#F7931E",
    "Needs Verification": "#F5D63D",
    "Potential Incident": "#E8505B",
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
    flag_z=3.5,             # flag a reading when |modified z| >= this
    persistence=3,          # consecutive flags needed for Potential Incident
    override_z=6.0,         # |z| at/above this can escalate without extra support
    r_unreliable=0.5,       # R below this = sensor unreliable
    r_incident=0.6,         # R needed for Potential Incident
    complaints_verify=3,    # complaints (sensors normal) -> Needs Verification
    complaints_support=2,   # complaints that count as support for an incident
    location_sensitivity=0.5,
    sampling_minutes=5,
)

DEMO_SITE_TYPES = ["Treatment plant outlet", "Storage reservoir / tank", "Distribution pipeline",
                   "Campus water point", "Borehole / groundwater", "Distribution pipeline",
                   "River / lake intake", "Storage reservoir / tank"]


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


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def show_plot(fig):
    """Plotly chart at full width (works on old and new Streamlit versions)."""
    try:
        st.plotly_chart(fig, width="stretch")
    except Exception:
        st.plotly_chart(fig, use_container_width=True)


def show_table(df):
    """Read-only table at full width (works on old and new Streamlit versions)."""
    try:
        st.dataframe(df, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)


def demo_config(i, name, lat, lon):
    lib = PARAMETER_LIBRARY["Water"]
    params = DEFAULT_PARAMS["Water"]
    return {
        "origin": "Pre-recorded (simulated)",
        "site_name": name,
        "sensor_id": f"WQ-{i:03d}",
        "domain": "Water",
        "site_type": DEMO_SITE_TYPES[(i - 1) % len(DEMO_SITE_TYPES)],
        "latitude": lat,
        "longitude": lon,
        "parameters": list(params),
        "ranges": {p: (lib[p]["vmin"], lib[p]["vmax"], lib[p]["typical"]) for p in params},
        **DEFAULT_CRITERIA,
        "contact": "",
        "notes": "",
    }


def init_state():
    if st.session_state.get("initialised"):
        return
    sites, readings, queue = load_demo_data()
    st.session_state.sites = sites.copy()
    st.session_state.readings = readings.copy()
    st.session_state.queue = queue.copy()
    st.session_state.configs = {
        row.site: demo_config(i, row.site, row.lat, row.lon)
        for i, row in enumerate(sites.itertuples(), start=1)
    }
    st.session_state.page = "welcome"        # welcome | dashboard | add_site
    st.session_state.current_site = None
    st.session_state.flash = None
    st.session_state.initialised = True


def go(page):
    st.session_state.page = page


def open_site_from_welcome():
    choice = st.session_state.get("welcome_choice")
    if choice:
        st.session_state.current_site = choice
        st.session_state.page = "dashboard"


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
    name = cfg["site_name"]
    times = (st.session_state.readings["timestamp"].drop_duplicates().sort_values().tolist())
    new_readings = simulate_baseline(name, cfg["domain"], cfg["ranges"], times)
    st.session_state.readings = pd.concat([st.session_state.readings, new_readings],
                                          ignore_index=True)
    new_row = pd.DataFrame([{"site": name, "lat": cfg["latitude"], "lon": cfg["longitude"],
                             "status": "Normal", "score": 0}])
    st.session_state.sites = pd.concat([st.session_state.sites, new_row], ignore_index=True)
    st.session_state.configs[name] = cfg
    st.session_state.current_site = name
    st.session_state.page = "dashboard"
    st.session_state.flash = (f"'{name}' added. Showing simulated baseline readings "
                              "until a real sensor feed is connected.")


def validate_new_site(cfg, ranges_ok_msgs):
    errors = list(ranges_ok_msgs)
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
    return errors


def config_rows(cfg):
    """Settings shown on the dashboard. Add new fields here as the form grows."""
    return [
        ("Sensor number / ID", cfg["sensor_id"]),
        ("Monitoring domain", cfg["domain"]),
        ("Type of site", cfg["site_type"]),
        ("Location (lat, lon)", f"{cfg['latitude']:.4f}, {cfg['longitude']:.4f}"),
        ("Parameters tracked", ", ".join(cfg["parameters"])),
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
# PAGE 1: Welcome
# ---------------------------------------------------------------------------
def page_welcome():
    st.markdown(
        f"""
        <style>
          .vf-hero {{ text-align:center; padding: 4.5rem 0 1.5rem 0; }}
          .vf-hero h1 {{ font-size: 4.2rem; margin: 0; color: {ORANGE}; letter-spacing: 1px; }}
          .vf-hero p  {{ font-size: 1.4rem; font-style: italic; opacity: .85; margin: .4rem 0 0 0; }}
        </style>
        <div class="vf-hero">
          <h1>🏮 VeriFlow</h1>
          <p>Evidence before alarm.</p>
        </div>
        """,
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
            st.button("➕  Add new site / sensor", on_click=go, args=("add_site",))
        st.caption("Pick an existing site to see its dashboard, or register a new site and sensor.")

    st.markdown("<br><br>", unsafe_allow_html=True)
    st.caption("Simulated-data prototype. Suspected incidents need human review "
               "and confirmatory testing.")


# ---------------------------------------------------------------------------
# PAGE 2b: Add new site / sensor
# ---------------------------------------------------------------------------
def page_add_site():
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
    latitude = c1.number_input("Latitude", -90.0, 90.0, 12.5, step=0.01, format="%.4f",
                               key="new_lat")
    longitude = c2.number_input("Longitude", -180.0, 180.0, 77.5, step=0.01, format="%.4f",
                                key="new_lon")

    # ---- 2. Fields to track -------------------------------------------------
    st.subheader("2. Fields to track")
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
    st.subheader("3. Flag event level and warning criteria")
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
    st.subheader("4. Contact and notes (optional)")
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
            "parameters": list(parameters), "ranges": ranges,
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


# ---------------------------------------------------------------------------
# PAGE 2a: Site dashboard (same layout as before)
# ---------------------------------------------------------------------------
def page_dashboard():
    sites = st.session_state.sites
    readings = st.session_state.readings
    queue = st.session_state.queue
    names = sites["site"].tolist()
    chosen_site = st.session_state.current_site
    cfg = st.session_state.configs[chosen_site]

    # Sidebar: navigation + site switcher
    st.sidebar.button("← Home", on_click=go, args=("welcome",))
    picked = st.sidebar.selectbox("Location", names, index=names.index(chosen_site))
    if picked != chosen_site:
        st.session_state.current_site = picked
        st.rerun()
    st.sidebar.button("➕ Add new site / sensor", on_click=go, args=("add_site",))

    if st.session_state.flash:
        st.toast(st.session_state.flash, icon="✅")
        st.session_state.flash = None

    # Header
    st.markdown("## 🏮 VeriFlow  <small style='color:#F7931E'>SIMULATED DATA</small>",
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

    # Map + trends
    left, right = st.columns([1, 2])
    with left:
        st.subheader("Map: status pins")
        map_df = sites.assign(selected=np.where(sites["site"] == chosen_site, 30, 16))
        fig_map = px.scatter(
            map_df, x="lon", y="lat", color="status", text="site", size="selected",
            size_max=18, color_discrete_map=STATUS_COLORS,
            hover_name="site", hover_data={"selected": False, "score": True,
                                            "lon": False, "lat": False},
        )
        fig_map.update_traces(textposition="top center")
        fig_map.update_layout(xaxis_visible=False, yaxis_visible=False,
                              legend_title_text="", height=380,
                              margin=dict(l=0, r=0, t=10, b=0))
        show_plot(fig_map)

    with right:
        st.subheader(f"Trends: last 2 h  ({chosen_site})")
        d = readings[readings["site"] == chosen_site].copy()
        if d.empty:
            st.info("No readings for this site yet.")
        else:
            d["type"] = np.where(d["flagged"], "Flagged", "Baseline")
            fig_tr = px.line(
                d, x="timestamp", y="value", color="type", facet_col="parameter",
                facet_col_wrap=2, markers=True,
                color_discrete_map={"Baseline": "#9E9E9E", "Flagged": "#E8505B"},
            )
            fig_tr.update_yaxes(matches=None, showticklabels=True)
            fig_tr.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            fig_tr.update_layout(height=380, legend_title_text="",
                                 margin=dict(l=0, r=0, t=30, b=0))
            show_plot(fig_tr)

    # Alert queue
    st.subheader("Alert queue")
    show_table(queue)
    st.caption("Queue: P1 Potential Incident, P2 Needs Verification; "
               "ties by Evidence Score x (0.7 + 0.3 x location sensitivity). "
               "Sample values are simulated.")

    # Alert detail
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

    # Site configuration (new)
    with st.expander("Site configuration"):
        show_table(pd.DataFrame(config_rows(cfg), columns=["Setting", "Value"]))
        rng_df = pd.DataFrame([
            {"Parameter": p, "Valid min": lo, "Valid max": hi, "Typical value": typ}
            for p, (lo, hi, typ) in cfg["ranges"].items()
        ])
        if not rng_df.empty:
            show_table(rng_df)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
init_state()
page = st.session_state.page
if page == "add_site":
    page_add_site()
elif page == "dashboard" and st.session_state.current_site:
    page_dashboard()
else:
    page_welcome()