# VeriFlow Design System

Reference look: a dark fintech dashboard. Near-black warm-brown canvas, translucent rounded
"glass" cards, an orange gradient for hero cards and primary actions, mint-green highlights,
white pill tooltips, pill-shaped segmented controls. Calm, premium, high contrast.
**This style applies to every screen, chart, map, form and pop-up. No exceptions.**

Implementation lives in `style.py`. This document is the human-readable version of it.

## 1. Colour tokens
| Token | Value | Use |
|---|---|---|
| bg | `#120D09` | page background (with two soft orange radial glows) |
| bg_2 | `#1A130E` | sidebar, raised panels, dropdowns |
| glass | `rgba(255,255,255,.045)` | card fill |
| glass_hi | `rgba(255,255,255,.08)` | hover / secondary buttons / inputs |
| border | `rgba(255,255,255,.09)` | 1px card and input outline |
| text | `#F6EEE6` | primary text |
| muted | `#9C9084` | labels, captions, axes |
| orange | `#F7931E` | brand accent, primary buttons, selection, focus |
| orange_deep | `#F26B1D` | end of the orange gradient |
| green | `#3DDC97` | positive / normal / healthy |
| yellow | `#F5D63D` | watch / needs verification |
| red | `#FF5A5F` | critical / potential incident / errors |
| grey | `#8C8279` | sensor fault, disabled |
| sky | `#7FD6FF` | sensor-location marker on maps only |

**Threat colours are semantic.** Normal = green, Watch = yellow, Flagged = orange,
Critical = red, Sensor fault = grey (striped). Never use them for decoration, and never
show a threat with a colour outside this set.

## 2. Typography
Plus Jakarta Sans (400/500/600/700/800), fallback Segoe UI / system-ui.
Headings 700, tight tracking (-0.01em). Big numbers 700 with -0.02em. Captions and labels use `muted`.

## 3. Shape and depth
* Cards: radius 22px, 1px `border`, `glass` fill, soft shadow `0 12px 32px rgba(0,0,0,.35)`.
* Inner controls: radius 14-16px. Buttons, tabs, radios, badges: full pill (999px).
* Hero / promo card: orange gradient `#FF9F2E -> #C25A12 -> #3A1E0C`, white text (`.vf-hero-card`).

## 4. Components
* **Primary button**: orange gradient, dark text `#1A0F06`, orange glow. One per view.
* **Secondary button**: glass pill, orange border + tint on hover.
* **Segmented control** (`st.radio(..., horizontal=True)`): glass pill track, selected option has orange tint and ring.
* **Metric card**: glass card, muted label, large bold value.
* **Inputs**: glass fill, 14px radius, orange border on focus.
* **Badge** (`.vf-badge`): orange outlined pill, small caps, e.g. SIMULATED DATA.
* **Reading-level bars / tanks**: glass container, threat colour fill, white tick = flag level, red tick = strong deviation.
* **Immediate-attention pop-up**: top right, dark red panel, red left border, pulsing glow.

## 5. Charts (Plotly)
Every figure goes through `style_figure(fig)`: transparent canvas, 6% white gridlines, muted axes,
orange default series, white pill tooltip with dark text. Lines 2.5px. Bars use threat colours.
Area/line hero charts: orange line over a fading orange fill.

## 6. Maps (Folium + real tiles)
* Built with `maps._base_map()`: keyless Esri Dark Gray tiles by default, Street and Satellite via the layer switch.
  CARTO tiles now need a free API key; set `CARTO_API_KEY` (env var or `.streamlit/secrets.toml`) to use them instead.
  Never use tile providers that show watermarks or need a hard-coded key.
* Status pins: 10px circles, white 2px outline, fill = status colour. Potential Incident gets a pulsing halo.
  Selected site gets an orange ring. Tooltip = white pill (`site · status · score`).
* Clicking a pin opens that site. Site picker: orange `S` pin, sensor: sky-blue `◉` pin, dashed line between them.
* The map sits in a rounded glass frame like any other card. A status legend sits bottom-left.

## 7. Layout
Wide layout, max width 1400px. Dashboard order (fixed): header, metric cards, then three glass
segments (keyed containers `vf_section_*`): **1. Alerts** (queue + detail, red accent, always first),
**2. Charts** (trends, own segment), **3. Map: status pins** (lower down). After that the live monitor
(reading levels, live graphs, sensor registry, tanks). Generous spacing, one idea per segment.
New dashboard areas get their own `vf_section_<name>` container; alerts must stay above everything else.

## 8. Do / Don't
* DO import colours from `style.py`; DO use glass cards and pill controls.
* DON'T add white or light backgrounds, default Streamlit blue/red accents, sharp 4px corners,
  emoji-heavy decoration, or a second accent colour.
* DON'T change the design system without an explicit request from the user.

## 9. Checklist before finishing any UI change
- [ ] Looks identical in style to the other pages (dark, glass, orange accent)
- [ ] No hard-coded hex colours outside `style.py`
- [ ] New charts use `style_figure`, new maps use `maps._base_map`
- [ ] Threat colours used only for threat meaning
- [ ] Tested at desktop width and on a narrow window
