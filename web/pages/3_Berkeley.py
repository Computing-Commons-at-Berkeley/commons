"""Berkeley / OSS: the curated watchlist and its last check time."""

from __future__ import annotations

import streamlit as st

from commons.config import load_watchlist_config
from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Berkeley", layout="wide")
settings = load_settings()
repo_path = settings.require_community_repo_path()

st.title("Berkeley / OSS")
st.caption("Live radar items appear in the weekly digest; this page shows the curated watchlist.")

watchlists = load_watchlist_config(repo_path / "config" / "watchlists.yaml")
state = {row["repo"]: row for row in data.watch_state(settings.news_db_path)}

for entry in watchlists.repositories:
    st.subheader(entry.repo)
    st.caption(f"category: {entry.category}")
    st.markdown(entry.reason)
    checked = state.get(entry.repo)
    st.caption(f"last checked: {checked['last_checked_at'] if checked else 'never'}")
    st.caption(f"watch: releases={entry.watch.releases} issues={entry.watch.issues}")
