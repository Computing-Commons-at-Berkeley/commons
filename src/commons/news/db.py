"""SQLite news and runtime state (plan section 26).

The schema is intentionally small: sources, news_items, watch_state, llm_usage.
No ORM, no entity graph. Deleting this database is an inconvenience, not a
disaster; durable community memory lives in Git.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from commons.config import SourceSpec
from commons.logging import get_logger

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    category TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_fetch_at TEXT,
    etag TEXT,
    last_modified TEXT,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    guid TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT,
    content_hash TEXT NOT NULL,
    processing_state TEXT NOT NULL DEFAULT 'new'
);

CREATE INDEX IF NOT EXISTS idx_news_items_published_at ON news_items(published_at);
CREATE INDEX IF NOT EXISTS idx_news_items_category ON news_items(category);
CREATE INDEX IF NOT EXISTS idx_news_items_content_hash ON news_items(content_hash);

CREATE TABLE IF NOT EXISTS watch_state (
    repo TEXT PRIMARY KEY,
    last_checked_at TEXT,
    state_json TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    operation TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0.0
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the runtime database."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def upsert_source(connection: sqlite3.Connection, source: SourceSpec) -> None:
    connection.execute(
        """
        INSERT INTO sources (id, type, url, category, enabled)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            type = excluded.type,
            url = excluded.url,
            category = excluded.category,
            enabled = excluded.enabled
        """,
        (source.id, source.type, source.url, source.category, int(source.enabled)),
    )
    connection.commit()


def get_source(connection: sqlite3.Connection, source_id: str) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


def record_source_fetch(
    connection: sqlite3.Connection,
    source_id: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    error: bool = False,
) -> None:
    now = datetime.now(UTC).isoformat()
    if error:
        connection.execute(
            "UPDATE sources SET last_fetch_at = ?, error_count = error_count + 1 WHERE id = ?",
            (now, source_id),
        )
    else:
        connection.execute(
            """
            UPDATE sources
            SET last_fetch_at = ?, etag = COALESCE(?, etag),
                last_modified = COALESCE(?, last_modified), error_count = 0
            WHERE id = ?
            """,
            (now, etag, last_modified, source_id),
        )
    connection.commit()
