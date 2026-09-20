"""Home page for the optional read-only local UI.

Reads COMMUNITY_REPO_PATH and RUNTIME_DIR via commons.settings. Read-only: it
never writes to Git or SQLite, and the community does not depend on it.
"""

from __future__ import annotations

import streamlit as st

from commons.settings import load_settings
from commons.web import data

st.set_page_config(page_title="Technical Commons", layout="wide")

settings = load_settings()
data_root = settings.require_community_repo_path() / "data"

st.title("Technical Commons")
st.caption("Read-only local companion. Discord and Git remain canonical.")

st.header("Latest digest")
digest = data.latest_digest(data_root)
if digest is None:
    st.info("No digests yet.")
else:
    st.caption(f"{digest.period_start.date()} to {digest.period_end.date()}")
    for section in digest.sections:
        st.subheader(section.heading)
        st.markdown(section.body)

st.header("Projects")
projects = data.projects(data_root)
if projects:
    for project in projects:
        st.markdown(f"- **{project.title}** ({project.status})")
else:
    st.info("No project records yet.")

st.header("Recent news (7d)")
news = data.news_items(settings.news_db_path, "7d", limit=5)
if news:
    for row in news:
        st.markdown(f"- [{row['title']}]({row['url']}) - {row['category']}")
else:
    st.info("No stored news yet. Run news ingestion first.")

knowledge = data.knowledge_artifacts(data_root)
st.header(f"Recent archives ({len(knowledge)})")
for item in knowledge[:10]:
    st.markdown(f"- {item.title}")
