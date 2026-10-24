"""
VeriFlow design system  -  SINGLE SOURCE OF TRUTH for look and feel.

Read DESIGN.md before changing any UI. Rules in short:
  * Never hard-code a colour, radius or font in app.py / maps.py. Import it from here.
  * Dark warm-brown "glass" surfaces, orange accent, mint-green for good / positive.
  * Charts go through style_figure(); maps use MAP_CSS; pages call inject_css() once.

Reference look: dark fintech dashboard (near-black brown canvas, translucent rounded
cards, orange gradient hero cards and primary buttons, mint-green highlight bars,
white "pill" tooltips, pill-shaped segmented controls).
"""
import streamlit as st

# ---------------------------------------------------------------------------
# 1. TOKENS
# ---------------------------------------------------------------------------
T = dict(
    # canvas + surfaces
    bg="#120D09",              # page background (warm near-black)
    bg_2="#1A130E",            # sidebar / raised areas
    glass="rgba(255,255,255,0.045)",
    glass_hi="rgba(255,255,255,0.08)",
    border="rgba(255,255,255,0.09)",
    # text
    text="#F6EEE6",
    muted="#9C9084",
    # brand + semantic
    orange="#F7931E",
    orange_deep="#F26B1D",
    orange_soft="rgba(247,147,30,0.16)",
    green="#3DDC97",           # positive / normal
    yellow="#F5D63D",          # watch / needs verification
    red="#FF5A5F",             # critical / incident
    grey="#8C8279",            # sensor fault / disabled
    sky="#7FD6FF",             # sensor-location marker (only use for map sensor pins)
    # shape
    r_lg="22px", r_md="16px", r_pill="999px",
    font="'Plus Jakarta Sans', 'Segoe UI', system-ui, -apple-system, sans-serif",
)

ORANGE = T["orange"]

STATUS_COLORS = {
    "Normal": T["green"],
    "Sensor Fault Suspected": T["orange"],
    "Needs Verification": T["yellow"],
    "Potential Incident": T["red"],
}
# Threat bands used by level bars, graphs, tanks (semantic: never reuse for decoration)
BAND_COLORS = {
    "Normal": T["green"],
    "Watch": T["yellow"],
    "Flagged": T["orange"],
    "Critical": T["red"],
    "Sensor fault": T["grey"],
}
BAND_EMOJI = {"Normal": "🟩", "Watch": "🟨", "Flagged": "🟧", "Critical": "🟥", "Sensor fault": "⬜"}


# ---------------------------------------------------------------------------
# 2. GLOBAL CSS
# ---------------------------------------------------------------------------
def _root_vars():
    pairs = {
        "bg": T["bg"], "bg2": T["bg_2"], "glass": T["glass"], "glass-hi": T["glass_hi"],
        "border": T["border"], "text": T["text"], "muted": T["muted"],
        "orange": T["orange"], "orange-deep": T["orange_deep"], "orange-soft": T["orange_soft"],
        "green": T["green"], "yellow": T["yellow"], "red": T["red"], "grey": T["grey"],
        "r-lg": T["r_lg"], "r-md": T["r_md"], "r-pill": T["r_pill"],
    }
    return ":root{" + ";".join(f"--vf-{k}:{v}" for k, v in pairs.items()) + "}"


CSS_STATIC = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

/* ---------- canvas ---------- */
.stApp, .stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5,
.stApp button, .stApp input, .stApp textarea, .stApp li, .stApp td, .stApp th {
    font-family: 'Plus Jakarta Sans', 'Segoe UI', system-ui, sans-serif;
}
[data-testid="stIconMaterial"], .material-icons, .material-symbols-rounded {
    font-family: 'Material Symbols Rounded' !important;
}
.stApp {
    color: var(--vf-text);
    background:
        radial-gradient(1100px 560px at 88% -8%, rgba(247,147,30,.17), transparent 60%),
        radial-gradient(900px 520px at -8% 108%, rgba(247,147,30,.09), transparent 60%),
        var(--vf-bg);
}
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1400px; }
h1, h2, h3, h4 { letter-spacing: -.01em; font-weight: 700; color: var(--vf-text); }
h3 { font-size: 1.2rem; }
small, .stCaption, [data-testid="stCaptionContainer"] { color: var(--vf-muted) !important; }
hr { border-color: var(--vf-border) !important; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.015)), var(--vf-bg2);
    border-right: 1px solid var(--vf-border);
}

/* ---------- glass cards: metrics, charts, forms, expanders, tables, maps ---------- */
[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(255,255,255,.075), rgba(255,255,255,.025));
    border: 1px solid var(--vf-border); border-radius: var(--vf-r-lg);
    padding: 1rem 1.25rem; box-shadow: 0 12px 32px rgba(0,0,0,.38);
}
[data-testid="stMetricLabel"] p { color: var(--vf-muted); font-size: .85rem; font-weight: 500; }
[data-testid="stMetricValue"] { font-weight: 700; letter-spacing: -.02em; }
[data-testid="stPlotlyChart"], [data-testid="stForm"], iframe[title*="folium"] {
    background: var(--vf-glass); border: 1px solid var(--vf-border);
    border-radius: var(--vf-r-lg); box-shadow: 0 12px 32px rgba(0,0,0,.3);
}
[data-testid="stPlotlyChart"] { padding: .5rem .6rem; }
[data-testid="stForm"] { padding: 1.4rem; }
iframe[title*="folium"] { overflow: hidden; }
[data-testid="stExpander"] {
    border: 1px solid var(--vf-border); border-radius: 18px; background: var(--vf-glass);
}
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: 1px solid var(--vf-border); border-radius: var(--vf-r-md); overflow: hidden;
}
[data-testid="stAlert"] {
    border-radius: var(--vf-r-md); border: 1px solid var(--vf-border); background: var(--vf-glass-hi);
}

/* ---------- buttons: pills, orange gradient for primary ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: var(--vf-r-pill); border: 1px solid var(--vf-border);
    background: var(--vf-glass-hi); color: var(--vf-text);
    padding: .45rem 1.2rem; font-weight: 600; transition: all .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
    border-color: var(--vf-orange); background: var(--vf-orange-soft); color: var(--vf-text);
}
button[kind="primary"], button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {
    background: linear-gradient(135deg, #FFA73A, var(--vf-orange-deep)) !important;
    border: none !important; color: #1A0F06 !important;
    box-shadow: 0 8px 22px rgba(247,147,30,.38);
}
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {
    filter: brightness(1.08); box-shadow: 0 10px 28px rgba(247,147,30,.5);
}

/* ---------- inputs ---------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
    background: rgba(255,255,255,.05) !important; border-radius: 14px !important;
    border: 1px solid var(--vf-border) !important;
}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within,
[data-baseweb="select"]:focus-within > div { border-color: var(--vf-orange) !important; }
[data-baseweb="popover"] ul { background: var(--vf-bg2) !important; }

/* ---------- radio = segmented pill control ("1 year | 6 month | 3 month") ---------- */
[data-testid="stRadio"] [role="radiogroup"] {
    display: inline-flex; flex-wrap: wrap; gap: .2rem; padding: .25rem;
    background: var(--vf-glass); border: 1px solid var(--vf-border); border-radius: var(--vf-r-pill);
}
[data-testid="stRadio"] label[data-baseweb="radio"] {
    margin: 0; padding: .3rem .95rem; border-radius: var(--vf-r-pill); cursor: pointer;
    transition: background .18s ease;
}
[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child { display: none; }
[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
    background: var(--vf-orange-soft); box-shadow: inset 0 0 0 1px var(--vf-orange);
}

/* ---------- toggles / sliders pick up the orange accent via config.toml primaryColor ---------- */

/* ---------- brand blocks ---------- */
.vf-hero { text-align:center; padding: 3rem 0 1.5rem 0; }
.vf-hero h1 { font-size: 4.2rem; margin: 0; color: var(--vf-orange); letter-spacing: 1px;
              text-shadow: 0 0 28px rgba(247,147,30,.4); font-weight: 800; }
.vf-hero p  { font-size: 1.35rem; font-style: italic; color: var(--vf-muted); margin: .4rem 0 0 0; }
.vf-auth-title { text-align:center; margin: .5rem 0 1rem 0; }
.vf-auth-title h1 { color: var(--vf-orange); margin: 0; font-size: 2.6rem; font-weight: 800; }
.vf-auth-title p { color: var(--vf-muted); font-style: italic; margin: .2rem 0 0 0; }
.vf-user { text-align:right; line-height:1.25; font-size:.95rem; }
.vf-badge { display:inline-block; padding:.15rem .7rem; margin-left:.5rem; border-radius: var(--vf-r-pill);
            font-size:.68rem; font-weight:700; letter-spacing:.08em; vertical-align:middle;
            color: var(--vf-orange); background: var(--vf-orange-soft); border:1px solid var(--vf-orange); }
.vf-hero-card { background: linear-gradient(135deg, #FF9F2E 0%, #C25A12 55%, #3A1E0C 100%);
                border-radius: var(--vf-r-lg); padding: 1.3rem 1.5rem; color: #FFF8F0;
                box-shadow: 0 16px 40px rgba(247,147,30,.25); }

/* ---------- reading-level bars ---------- */
.vf-lvls { display:flex; flex-direction:column; gap:.95rem; margin:.4rem 0 .6rem 0;
           background: var(--vf-glass); border:1px solid var(--vf-border);
           border-radius: var(--vf-r-lg); padding: 1.1rem 1.3rem; }
.vf-lvl-head { display:flex; justify-content:space-between; font-size:.95rem; margin-bottom:.25rem; }
.vf-lvl-track { position:relative; height:14px; border-radius:10px;
                background: rgba(255,255,255,.08); overflow:hidden; }
.vf-lvl-fill { height:100%; border-radius:10px; transition: width .6s ease, background-color .6s ease; }
.vf-striped { background-image: repeating-linear-gradient(45deg, rgba(0,0,0,.28) 0 8px, transparent 8px 16px); }
.vf-tick { position:absolute; top:0; bottom:0; width:2px; background: rgba(255,255,255,.7); }
.vf-tick-crit { background: var(--vf-red); }
.vf-lvl-note { font-size:.8rem; margin-top:.2rem; }
.vf-legend { font-size:.82rem; color: var(--vf-muted); margin-bottom:.4rem; }

/* ---------- water-level tanks ---------- */
.vf-tank-site { font-weight:600; margin:.8rem 0 .1rem 0; color: var(--vf-orange); }
.vf-tanks { display:flex; flex-wrap:wrap; gap:1.3rem; margin:.5rem 0 1rem 0;
            background: var(--vf-glass); border:1px solid var(--vf-border);
            border-radius: var(--vf-r-lg); padding: 1.1rem 1.3rem; }
.vf-tank-wrap { display:flex; flex-direction:column; align-items:center; width:110px; text-align:center; }
.vf-tank { position:relative; width:84px; height:140px; border:3px solid rgba(255,255,255,.5);
           border-top-width:1px; border-radius:6px 6px 22px 22px; overflow:hidden;
           background: rgba(0,0,0,.28); }
.vf-tank.mini { width:58px; height:92px; }
.vf-water { position:absolute; left:0; right:0; bottom:0; background-color: var(--c);
            opacity:.88; transition: height .8s ease; }
.vf-wave { position:absolute; left:0; top:-9px; width: calc(100% + 40px); height:10px;
           background: radial-gradient(circle at 10px -2px, transparent 12px, var(--c) 13px);
           background-size: 20px 10px; background-repeat: repeat-x;
           animation: vf-wave-move 2.6s linear infinite; }
.vf-still .vf-wave { animation:none; display:none; }
@keyframes vf-wave-move { from { transform: translateX(0); } to { transform: translateX(-20px); } }
.vf-tank-val { position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
               font-weight:700; font-size:1rem; text-shadow: 0 1px 3px rgba(0,0,0,.9); z-index:2; }
.vf-tank.mini .vf-tank-val { font-size:.78rem; }
.vf-tank-label { margin-top:.35rem; font-weight:600; font-size:.9rem; }
.vf-tank-sub { font-size:.74rem; color: var(--vf-muted); }

/* ---------- immediate-attention pop-up (keyed container pinned right) ---------- */
.st-key-vf_alert_panel { position: fixed; top: 4.2rem; right: 1.2rem; width: min(370px, 92vw);
    max-height: 72vh; overflow-y: auto; z-index: 1000000; background: #2B1215;
    border: 1px solid var(--vf-red); border-left: 7px solid var(--vf-red); border-radius: var(--vf-r-md);
    padding: .8rem 1rem; box-shadow: 0 8px 30px rgba(255,90,95,.45);
    animation: vf-slide .4s ease-out, vf-pulse 2.2s ease-in-out infinite; }
@keyframes vf-slide { from { transform: translateX(120%); opacity:0; } to { transform:none; opacity:1; } }
@keyframes vf-pulse { 0%,100% { box-shadow: 0 8px 30px rgba(255,90,95,.30); }
                      50% { box-shadow: 0 8px 38px rgba(255,90,95,.85); } }
"""


def inject_css():
    """Call once per run, right after set_page_config."""
    st.markdown(f"<style>{_root_vars()}{CSS_STATIC}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 3. CHARTS (Plotly): every figure goes through style_figure()
# ---------------------------------------------------------------------------
def style_figure(fig, height=None):
    """Dark-glass chart look: transparent canvas, faint grid, white pill tooltip."""
    grid = "rgba(255,255,255,0.06)"
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=T["font"], color=T["muted"], size=12),
        colorway=[T["orange"], T["green"], T["yellow"], T["sky"], T["red"]],
        hoverlabel=dict(bgcolor="#FFFFFF", font=dict(color="#1A0F06", family=T["font"])),
        legend=dict(font=dict(color=T["muted"]), bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=grid, zerolinecolor=grid, linecolor=grid, tickfont=dict(color=T["muted"]))
    fig.update_yaxes(gridcolor=grid, zerolinecolor=grid, linecolor=grid, tickfont=dict(color=T["muted"]))
    fig.for_each_annotation(lambda a: a.update(font=dict(color=T["text"], size=13)))
    if height:
        fig.update_layout(height=height)
    return fig


# ---------------------------------------------------------------------------
# 4. MAPS (CSS injected inside the folium iframe, see maps.py)
# ---------------------------------------------------------------------------
MAP_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700&display=swap');
.leaflet-container {{ background:{T['bg']}; font-family:{T['font']}; }}
.leaflet-tooltip {{ background:#FFFFFF; color:#1A0F06; border:none; border-radius:12px;
                    padding:.35rem .7rem; font-weight:600; box-shadow:0 6px 18px rgba(0,0,0,.4); }}
.leaflet-tooltip-top:before {{ border-top-color:#FFFFFF; }}
.leaflet-control-layers, .leaflet-bar a {{ background:{T['bg_2']}; color:{T['text']};
                    border:1px solid {T['border']}; border-radius:12px; }}
.leaflet-bar a {{ border-radius:0; }}
.leaflet-control-layers-expanded {{ padding:.5rem .7rem; }}
.leaflet-control-attribution {{ background:rgba(18,13,9,.7)!important; color:{T['muted']}!important; }}
.leaflet-control-attribution a {{ color:{T['muted']}!important; }}
.vf-halo {{ animation: vfp 2.2s ease-in-out infinite; }}
@keyframes vfp {{ 0%,100% {{ fill-opacity:.12; }} 50% {{ fill-opacity:.45; }} }}
.vf-pin {{ width:30px; height:30px; border-radius:50%; background:var(--c); color:#1A0F06;
           display:flex; align-items:center; justify-content:center; font-weight:800; font-size:13px;
           border:2px solid #FFFFFF; box-shadow:0 4px 14px rgba(0,0,0,.55); }}
.vf-legend-map {{ position:absolute; bottom:22px; left:12px; z-index:999; padding:.55rem .8rem;
           background:rgba(26,19,14,.88); border:1px solid {T['border']}; border-radius:14px;
           color:{T['text']}; font-size:12px; line-height:1.55; backdrop-filter:blur(8px); }}
.vf-legend-map i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }}
</style>
"""
