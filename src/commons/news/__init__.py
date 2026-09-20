"""News pipeline: SQLite runtime state, normalization, ingestion, and queries.

News is a pipeline, not a Discord channel (spec section 16). The full corpus
lives in SQLite under RUNTIME_DIR; Git stores only digests and deliberately
archived items. Deterministic dedup happens before any LLM call.
"""

from commons.news.db import connect, init_db
from commons.news.ingest import IngestionResult, NewsItem, ingest_source, parse_feed
from commons.news.normalize import canonicalize_url, content_hash
from commons.news.query import items_for_window, items_since, window_since

__all__ = [
    "IngestionResult",
    "NewsItem",
    "canonicalize_url",
    "connect",
    "content_hash",
    "ingest_source",
    "init_db",
    "items_for_window",
    "items_since",
    "parse_feed",
    "window_since",
]
