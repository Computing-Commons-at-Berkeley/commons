"""Optional read-only local UI (plan sections 40-42).

The UI is a disposable companion: it reads Git Markdown and the runtime SQLite
database, never writes, and no core community workflow depends on it.
"""

from commons.web.data import (
    SearchHit,
    digests,
    knowledge_artifacts,
    latest_digest,
    news_items,
    projects,
    resources,
    search,
    watch_state,
)

__all__ = [
    "SearchHit",
    "digests",
    "knowledge_artifacts",
    "latest_digest",
    "news_items",
    "projects",
    "resources",
    "search",
    "watch_state",
]
