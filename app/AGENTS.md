# Instructions for any AI agent or developer working on VeriFlow

1. **Before touching any UI, read `DESIGN.md`.** The visual style is fixed and must be
   identical on every page, in every chart and on every map.
2. **`style.py` is the single source of truth** for colours, fonts, radii, CSS, chart theme and
   map CSS. Never hard-code a hex colour, font or radius in `app.py` or `maps.py`; import from `style.py`.
3. New chart -> build it, then pass it through `style_figure(fig)`.
   New map -> build it with `maps._base_map()` so it gets the dark tiles and map CSS.
   New page -> `inject_css()` is already called in the router; do not add page-specific themes.
4. Keep `.streamlit/config.toml` in sync with the tokens in `style.py` if you change any colour.
5. Do not restyle, rename or "modernise" the design system unless the user explicitly asks.
   If a request conflicts with `DESIGN.md`, follow `DESIGN.md` and tell the user.
6. Run `pip install -r requirements.txt` then `streamlit run app.py` to check your change.
