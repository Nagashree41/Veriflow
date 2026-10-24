"""
VeriFlow maps (real tiles, dark theme from style.py).

  status_map(...)      dashboard map with one coloured pin per site (click a pin to open that site)
  location_picker(...) add-site map: click to place the SITE and the SENSOR

Needs:  pip install folium streamlit-folium
Without them the dashboard falls back to a plain Plotly map and the picker falls back to
number boxes, so the app never crashes.
"""
import math
import os

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from style import MAP_CSS, STATUS_COLORS, T, ORANGE, style_figure

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except Exception:          # not installed
    HAS_FOLIUM = False

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
TILES = {   # all keyless (no account needed)
    "Dark": (f"{ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
             "Tiles © Esri, HERE, Garmin, OpenStreetMap contributors", 16),
    "Street": (f"{ESRI}/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}", "Tiles © Esri", 19),
    "Satellite": (f"{ESRI}/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}", "Tiles © Esri", 19),
}


def _carto_key():
    """Optional free CARTO key (carto.com/basemaps/apikey). Set env CARTO_API_KEY or
    .streamlit/secrets.toml -> CARTO_API_KEY = "..." to use CARTO's dark basemap instead of Esri's."""
    key = os.environ.get("CARTO_API_KEY")
    if not key:
        try:
            key = st.secrets.get("CARTO_API_KEY")
        except Exception:
            key = None
    return key


def _tile_set():
    tiles = dict(TILES)
    key = _carto_key()
    if key:
        carto = {"Dark": (f"https://basemaps.cartocdn.com/rastertiles/dark_all/{{z}}/{{x}}/{{y}}.png?key={key}",
                          "© OpenStreetMap contributors © CARTO", 19)}
        tiles = {**carto, **{k: v for k, v in tiles.items() if k != "Dark"}}
    return tiles


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _base_map(center, zoom):
    m = folium.Map(location=list(center), zoom_start=int(zoom), tiles=None,
                   control_scale=True, zoom_control=True)
    for i, (name, (url, attr, maxz)) in enumerate(_tile_set().items()):
        folium.TileLayer(tiles=url, attr=attr, name=name, show=(i == 0), max_zoom=maxz).add_to(m)
    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    m.get_root().header.add_child(folium.Element(MAP_CSS))
    return m


def _pin(label, colour):
    return folium.DivIcon(html=f"<div class='vf-pin' style='--c:{colour}'>{label}</div>",
                          icon_size=(30, 30), icon_anchor=(15, 15))


def _render(m, key, height, returned):
    kwargs = dict(key=key, height=height, returned_objects=returned)
    try:
        return st_folium(m, use_container_width=True, **kwargs)
    except TypeError:                          # newer/older signature
        try:
            return st_folium(m, width=None, **kwargs)
        except TypeError:
            return st_folium(m, width=900, **kwargs)


def _legend_html():
    items = "".join(f"<div><i style='background:{c}'></i>{s}</div>" for s, c in STATUS_COLORS.items())
    return f"<div class='vf-legend-map'>{items}</div>"


# ---------------------------------------------------------------------------
# Dashboard: status pins
# ---------------------------------------------------------------------------
def status_map(sites, configs, chosen, key="vf_status_map", height=400):
    """Draw every site as a status-coloured pin. Returns the name of a clicked site (or None)."""
    if sites.empty:
        st.info("No sites yet.")
        return None

    if not HAS_FOLIUM:
        _fallback_status_map(sites, chosen, height)
        return None

    lats, lons = sites["lat"].astype(float), sites["lon"].astype(float)
    m = _base_map((lats.mean(), lons.mean()), 9)
    if len(sites) > 1:
        m.fit_bounds([[lats.min(), lons.min()], [lats.max(), lons.max()]], padding=(40, 40))

    for r in sites.itertuples():
        colour = STATUS_COLORS.get(r.status, T["grey"])
        tip = f"{r.site} · {r.status} · score {r.score}"
        if r.status == "Potential Incident":                      # pulsing halo
            folium.CircleMarker([r.lat, r.lon], radius=24, color=colour, weight=0, fill=True,
                                fill_color=colour, fill_opacity=.3, interactive=False,
                                class_name="vf-halo").add_to(m)
        folium.CircleMarker([r.lat, r.lon], radius=10, color="#FFFFFF", weight=2, fill=True,
                            fill_color=colour, fill_opacity=.95, tooltip=tip).add_to(m)
        if r.site == chosen:                                       # selection ring
            folium.CircleMarker([r.lat, r.lon], radius=17, color=ORANGE, weight=3, fill=False,
                                interactive=False).add_to(m)

    cfg = configs.get(chosen)                                      # sensor of the selected site
    if cfg and cfg.get("sensor_latitude") is not None:
        s_lat, s_lon = cfg["sensor_latitude"], cfg["sensor_longitude"]
        if distance_m(cfg["latitude"], cfg["longitude"], s_lat, s_lon) > 5:
            folium.PolyLine([[cfg["latitude"], cfg["longitude"]], [s_lat, s_lon]], color=T["sky"],
                            weight=2, dash_array="4", interactive=False).add_to(m)
            folium.CircleMarker([s_lat, s_lon], radius=5, color=T["sky"], weight=2, fill=True,
                                fill_color=T["sky"], fill_opacity=1,
                                tooltip=f"Sensor {cfg['sensor_id']}").add_to(m)

    m.get_root().html.add_child(folium.Element(_legend_html()))
    out = _render(m, key, height, ["last_object_clicked_tooltip"])
    tip = (out or {}).get("last_object_clicked_tooltip")
    return tip.split(" · ")[0].strip() if tip else None


def _fallback_status_map(sites, chosen, height):
    st.caption("Install `folium` and `streamlit-folium` for the interactive map.")
    df = sites.assign(size=np.where(sites["site"] == chosen, 18, 11))
    kw = dict(lat="lat", lon="lon", color="status", size="size", size_max=18, hover_name="site",
              hover_data={"size": False, "lat": False, "lon": False, "score": True},
              color_discrete_map=STATUS_COLORS, zoom=7)
    layer = dict(below="traces", sourcetype="raster", sourceattribution="Tiles © Esri",
                 source=[TILES["Dark"][0]])
    try:
        fig = px.scatter_map(df, map_style="white-bg", **kw)
        fig.update_layout(map_layers=[layer])
    except Exception:
        fig = px.scatter_mapbox(df, mapbox_style="white-bg", **kw)
        fig.update_layout(mapbox_layers=[layer])
    fig.update_layout(height=height, legend_title_text="", margin=dict(l=0, r=0, t=0, b=0))
    style_figure(fig)
    try:
        st.plotly_chart(fig, width="stretch", key="vf_status_map_fallback")
    except Exception:
        st.plotly_chart(fig, use_container_width=True, key="vf_status_map_fallback")


# ---------------------------------------------------------------------------
# Add-site: click-to-place picker
# ---------------------------------------------------------------------------
PICK_DEFAULTS = {
    "new_pick_target": "Site location",
    "new_same_loc": True,
    "new_map_zoom": 10,
    "new_last_click": None,
}


def location_picker(sites, height=430):
    """Renders the picker and returns {'site': (lat, lon), 'sensor': (lat, lon)}."""
    ss = st.session_state
    ctr = (round(float(sites["lat"].mean()), 4), round(float(sites["lon"].mean()), 4)) if len(sites) \
        else (12.5, 77.5)
    for k, v in {**PICK_DEFAULTS, "new_site_lat": ctr[0], "new_site_lon": ctr[1],
                 "new_sensor_lat": ctr[0], "new_sensor_lon": ctr[1]}.items():
        ss.setdefault(k, v)

    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    c1.radio("Click the map to place", ["Site location", "Sensor location"], key="new_pick_target",
             horizontal=True)
    c2.checkbox("Sensor is at the site", key="new_same_loc",
                help="Untick to place the sensor at a different spot (for example a tank outlet).")

    if HAS_FOLIUM:
        target = "site" if ss.new_pick_target.startswith("Site") else "sensor"
        centre = (ss[f"new_{target}_lat"], ss[f"new_{target}_lon"])
        m = _base_map(centre, ss.new_map_zoom)

        for r in sites.itertuples():                                # existing sites for context
            folium.CircleMarker([r.lat, r.lon], radius=5, color="#FFFFFF", weight=1, fill=True,
                                fill_color=STATUS_COLORS.get(r.status, T["grey"]), fill_opacity=.8,
                                interactive=False).add_to(m)

        site_pt = [ss.new_site_lat, ss.new_site_lon]
        sensor_pt = [ss.new_sensor_lat, ss.new_sensor_lon]
        folium.Marker(site_pt, icon=_pin("S", T["orange"]), tooltip="New site",
                      interactive=False).add_to(m)
        if not ss.new_same_loc:
            folium.PolyLine([site_pt, sensor_pt], color=T["sky"], weight=2, dash_array="5",
                            interactive=False).add_to(m)
            folium.Marker(sensor_pt, icon=_pin("◉", T["sky"]), tooltip="Sensor",
                          interactive=False).add_to(m)

        out = _render(m, "vf_pick_map", height, ["last_clicked", "zoom"])
        if out:
            if out.get("zoom"):
                ss.new_map_zoom = int(out["zoom"])
            click = out.get("last_clicked")
            if click and click != ss.new_last_click:                # a NEW click: apply it once
                ss.new_last_click = dict(click)
                lat, lon = round(float(click["lat"]), 5), round(float(click["lng"]), 5)
                if target == "site" or ss.new_same_loc:
                    ss.new_site_lat, ss.new_site_lon = lat, lon
                if target == "sensor" or ss.new_same_loc:
                    ss.new_sensor_lat, ss.new_sensor_lon = lat, lon
                st.rerun()
        st.caption("Orange S = site, blue ◉ = sensor. Switch the layer (top right of the map) to "
                   "Satellite for precise placement, or fine-tune the numbers below.")
    else:
        st.warning("Interactive map not installed. Run `pip install folium streamlit-folium`, "
                   "then restart. Until then, type the coordinates below.")

    if ss.new_same_loc:                                             # keep sensor glued to site
        ss.new_sensor_lat, ss.new_sensor_lon = ss.new_site_lat, ss.new_site_lon

    a, b, c, d = st.columns(4)
    a.number_input("Site latitude", -90.0, 90.0, key="new_site_lat", step=0.0001, format="%.5f")
    b.number_input("Site longitude", -180.0, 180.0, key="new_site_lon", step=0.0001, format="%.5f")
    c.number_input("Sensor latitude", -90.0, 90.0, key="new_sensor_lat", step=0.0001, format="%.5f",
                   disabled=bool(ss.new_same_loc))
    d.number_input("Sensor longitude", -180.0, 180.0, key="new_sensor_lon", step=0.0001, format="%.5f",
                   disabled=bool(ss.new_same_loc))

    if not ss.new_same_loc:
        dist = distance_m(ss.new_site_lat, ss.new_site_lon, ss.new_sensor_lat, ss.new_sensor_lon)
        st.caption(f"Sensor is {dist:,.0f} m from the site centre.")

    return {"site": (float(ss.new_site_lat), float(ss.new_site_lon)),
            "sensor": (float(ss.new_sensor_lat), float(ss.new_sensor_lon))}
