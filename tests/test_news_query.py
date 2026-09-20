from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from commons.news import db
from commons.news.query import NewsQueryError, items_for_window, items_since, window_since

ROWS = [
    ("ml", "2026-01-08T00:00:00+00:00", "recent"),
    ("ml", "2026-01-03T00:00:00+00:00", "week"),
    ("infra", "2025-12-15T00:00:00+00:00", "month"),
    ("infra", "2025-06-01T00:00:00+00:00", "old"),
]


def seed(connection) -> None:
    for index, (category, published, title) in enumerate(ROWS):
        connection.execute(
            """
            INSERT INTO news_items
                (source_id, title, url, canonical_url, published_at, fetched_at,
                 category, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s",
                title,
                f"https://e.test/{index}",
                f"https://e.test/{index}",
                published,
                published,
                category,
                f"h{index}",
            ),
        )
    connection.commit()


def test_one_corpus_multiple_views(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    seed(connection)
    now = datetime(2026, 1, 9, tzinfo=UTC)

    assert [row["title"] for row in items_for_window(connection, "24h", now=now)] == ["recent"]
    assert [row["title"] for row in items_for_window(connection, "7d", now=now)] == [
        "recent",
        "week",
    ]
    assert [row["title"] for row in items_for_window(connection, "30d", now=now)] == [
        "recent",
        "week",
        "month",
    ]
    assert [
        row["title"] for row in items_for_window(connection, "30d", now=now, category="ml")
    ] == ["recent", "week"]


def test_window_since_rejects_unknown_label() -> None:
    with pytest.raises(NewsQueryError):
        window_since("2w")


def test_items_since_limit(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    seed(connection)
    rows = items_since(connection, datetime(2020, 1, 1, tzinfo=UTC), limit=2)
    assert len(rows) == 2
