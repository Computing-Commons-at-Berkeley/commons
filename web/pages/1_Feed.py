"""Feed: temporal news views over one corpus."""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Feed", layout="wide")
settings = load_settings()

st.title("Feed")
window = st.radio("Window", ["24h", "7d", "30d"], index=1, horizontal=True)
category = st.selectbox("Category", ["all", "ml", "infra", "economics", "berkeley"])

rows = data.news_items(
    settings.news_db_path,
    window,
    category=None if category == "all" else category,
)
st.caption(f"{len(rows)} item(s)")
for row in rows:
    st.markdown(f"**[{row['title']}]({row['url']})** - {row['category']}")
if not rows:
    st.info("No stored items for this window. Run news ingestion first.")
