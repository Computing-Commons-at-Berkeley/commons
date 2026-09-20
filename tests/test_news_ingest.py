from __future__ import annotations

from pathlib import Path

import httpx

from commons.config import SourceSpec
from commons.news import db
from commons.news.ingest import ingest_source, parse_feed, store_items

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Example</title>
<item>
  <title>{title}</title>
  <link>{link}</link>
  <guid>{guid}</guid>
  <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
  <description>  Summary   text  </description>
</item>
</channel></rss>"""


def rss_bytes(
    *,
    title: str = "Hello",
    link: str = "https://example.com/a",
    guid: str = "g1",
) -> bytes:
    return RSS.format(title=title, link=link, guid=guid).encode("utf-8")


def make_source(**overrides: object) -> SourceSpec:
    data: dict[str, object] = {
        "id": "example",
        "type": "rss",
        "url": "https://example.com/feed.xml",
        "category": "ml",
    }
    data.update(overrides)
    return SourceSpec.model_validate(data)


def test_parse_feed_normalizes_and_dates() -> None:
    items = parse_feed(rss_bytes(), make_source())
    assert len(items) == 1
    item = items[0]
    assert item.title == "Hello"
    assert item.canonical_url == "https://example.com/a"
    assert item.published_at is not None
    assert item.published_at.startswith("2026-01-01T00:00:00")
    assert item.summary == "Summary text"
    assert item.content_hash


def test_parse_feed_skips_incomplete_entries() -> None:
    content = (
        b'<?xml version="1.0"?><rss version="2.0"><channel>'
        b"<item><title>No link</title></item></channel></rss>"
    )
    assert parse_feed(content, make_source()) == []


def test_store_items_is_deterministic(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    source = make_source()

    assert store_items(connection, parse_feed(rss_bytes(), source)) == (1, 0)
    assert store_items(connection, parse_feed(rss_bytes(), source)) == (0, 1)

    # Same article via a tracking-parameter variant dedups by canonical URL.
    variant = parse_feed(rss_bytes(link="https://example.com/a?utm_source=x", guid="g2"), source)
    assert store_items(connection, variant) == (0, 1)


def test_ingest_rss_source_records_etag(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rss_bytes(), headers={"ETag": "abc"})

    result = ingest_source(connection, make_source(), transport=httpx.MockTransport(handler))
    assert result.inserted == 1
    assert result.error is None
    assert db.get_source(connection, "example")["etag"] == "abc"


def test_ingest_source_records_error_without_crashing(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = ingest_source(connection, make_source(), transport=httpx.MockTransport(handler))
    assert result.error is not None
    assert result.inserted == 0
    assert db.get_source(connection, "example")["error_count"] == 1


def test_ingest_source_honours_not_modified(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    db.upsert_source(connection, make_source())
    db.record_source_fetch(connection, "example", etag="abc")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("If-None-Match") == "abc"
        return httpx.Response(304)

    result = ingest_source(connection, make_source(), transport=httpx.MockTransport(handler))
    assert result.not_modified is True
    assert result.inserted == 0


def test_ingest_github_releases(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)
    payload = [
        {
            "id": 1,
            "name": "v1.0",
            "html_url": "https://github.com/example/project/releases/tag/v1.0",
            "published_at": "2026-01-01T00:00:00Z",
            "body": "Release notes",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/repos/example/project/releases")
        return httpx.Response(200, json=payload)

    source = make_source(
        id="releases",
        type="github_release",
        url="https://github.com/example/project",
        category="infra",
    )
    result = ingest_source(connection, source, transport=httpx.MockTransport(handler))
    assert result.inserted == 1
    assert result.error is None
