from __future__ import annotations

from pathlib import Path

import httpx

from commons.news.run import run_ingestion
from commons.settings import Settings

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Hello</title>
  <link>https://example.com/a</link>
  <guid>g1</guid>
  <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""

SOURCES = """sources:
  - id: example
    type: rss
    url: https://example.com/feed.xml
    category: ml
"""


def make_settings(tmp_path: Path) -> Settings:
    community = tmp_path / "community"
    (community / "config").mkdir(parents=True)
    (community / "config" / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    return Settings(
        _env_file=None,
        community_repo_path=community,
        runtime_dir=tmp_path / "runtime",
    )


def test_run_ingestion_then_dedups(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    first = run_ingestion(settings, transport=transport)
    assert first[0].inserted == 1

    second = run_ingestion(settings, transport=transport)
    assert second[0].inserted == 0
    assert second[0].skipped == 1


def test_prune_news_items_applies_retention(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from commons.news import db as news_db
    from commons.news.run import prune_news_items

    settings = make_settings(tmp_path)
    connection = news_db.connect(settings.news_db_path)
    news_db.init_db(connection)
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    connection.execute(
        """
        INSERT INTO news_items
            (source_id, title, url, canonical_url, published_at, fetched_at,
             category, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s", "Old", "https://e.test/old", "https://e.test/old", old, old, "ml", "h1"),
    )
    connection.commit()
    connection.close()

    assert prune_news_items(settings, retention_days=30) == 1
    assert prune_news_items(settings, retention_days=30) == 0
