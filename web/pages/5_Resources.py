"""Resources: curated resource notes under data/resources."""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Resources", layout="wide")
settings = load_settings()
data_root = settings.require_community_repo_path() / "data"

st.title("Resources")
files = data.resources(data_root)
for path in files:
    st.subheader(path.stem)
    st.markdown(path.read_text(encoding="utf-8"))
if not files:
    st.info("No resource notes yet.")
