"""
Entry point that runs the UNMODIFIED app.py on real pipeline data.

    streamlit run veriflow_app.py

(`streamlit run app.py` still works and shows app.py's built-in dummy data.)
All it does is install two hooks from bridge.py and then execute app.py as __main__.
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402  (no st.* call may happen before app.py's set_page_config)

import bridge  # noqa: E402
import style  # noqa: E402

bridge.install_hooks(st, style)
runpy.run_path(str(ROOT / "app.py"), run_name="__main__")
