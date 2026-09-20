"""Projects: active, paused, and archived project records."""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Projects", layout="wide")
settings = load_settings()
data_root = settings.require_community_repo_path() / "data"

st.title("Projects")
projects = data.projects(data_root)
for status in ("active", "paused", "archived"):
    group = [project for project in projects if project.status == status]
    st.subheader(f"{status} ({len(group)})")
    for project in group:
        with st.expander(project.title):
            st.markdown(f"**Goal:** {project.goal or '-'}")
            st.markdown(f"**Members:** {', '.join(project.members) or '-'}")
            st.markdown(f"**Current state:** {project.current_state or '-'}")
            st.markdown(f"**Repo:** {project.repo or '-'}")
            st.markdown(f"**Discord thread:** {project.discord_thread_id or '-'}")
