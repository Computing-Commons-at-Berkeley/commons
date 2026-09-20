"""Search: simple text search over Markdown artifacts and news metadata."""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Search", layout="wide")
settings = load_settings()
data_root = settings.require_community_repo_path() / "data"

st.title("Search")
query = st.text_input("Query")
if query:
    hits = data.search(data_root, settings.news_db_path, query)
    st.caption(f"{len(hits)} hit(s)")
    for hit in hits:
        st.markdown(f"**[{hit.kind}] {hit.title}**")
        st.caption(hit.location)
        st.markdown(hit.snippet)
