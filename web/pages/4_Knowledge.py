"""Knowledge: browse durable archive artifacts."""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Knowledge", layout="wide")
settings = load_settings()
data_root = settings.require_community_repo_path() / "data"

st.title("Knowledge")
items = data.knowledge_artifacts(data_root)
for item in items:
    with st.expander(item.title):
        st.markdown(item.summary)
        if item.key_points:
            st.markdown("**Key points**")
            for point in item.key_points:
                st.markdown(f"- {point}")
        if item.open_questions:
            st.markdown("**Open questions**")
            for question in item.open_questions:
                st.markdown(f"- {question}")
        if item.tags:
            st.caption("tags: " + ", ".join(item.tags))
if not items:
    st.info("No archived notes yet. Use /archive in Discord.")
