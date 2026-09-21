"""RSS and GitHub-release ingestion into SQLite (plan sections 27-29).

Only metadata and a short derived summary are stored; full article text is not
persisted (spec section 19). Deduplication is deterministic and happens before
anything would call the LLM.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

from commons.config import SourceSpec
from commons.logging import get_logger
from commons.news import db, normalize

log = get_logger(__name__)

USER_AGENT = "computing-commons/0.1 (+https://github.com/Computing-Commons-at-Berkeley)"
MAX_SUMMARY_CHARS = 500


@dataclass(frozen=True)
class NewsItem:
    source_id: str
    title: str
    url: str
    canonical_url: str
    category: str
    published_at: str | None = None
    guid: str | None = None
    summary: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class IngestionResult:
    source_id: str
    fetched: int
    inserted: int
    skipped: int
    error: str | None = None
    not_modified: bool = False
    consecutive_failures: int = 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(value: Any) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    return text[:MAX_SUMMARY_CHARS] if text else None


def _entry_published(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=UTC).isoformat()
    return None


def _iso(value: Any) -> str | None:
    """Normalize a timestamp to ISO 8601 so SQLite string comparison is sound."""

    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return text or None


def _make_item(source: SourceSpec, title: str, url: str, **extra: Any) -> NewsItem:
    canonical = normalize.canonicalize_url(url)
    return NewsItem(
        source_id=source.id,
        title=title,
        url=url,
        canonical_url=canonical,
        category=source.category,
        content_hash=normalize.content_hash(title, canonical),
        **extra,
    )


def parse_feed(content: bytes, source: SourceSpec) -> list[NewsItem]:
    """Parse RSS/Atom bytes into normalized items."""

    parsed = feedparser.parse(content)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        if not title or not link:
            continue
        guid = entry.get("id") or entry.get("guid")
        items.append(
            _make_item(
                source,
                title,
                link,
                published_at=_entry_published(entry),
                guid=str(guid) if guid else None,
                summary=_truncate(entry.get("summary")),
            )
        )
    return items


def fetch_rss(
    source: SourceSpec,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> tuple[list[NewsItem], dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
        response = client.get(source.url, headers=headers)
    if response.status_code == 304:
        return [], {"not_modified": True}
    response.raise_for_status()
    meta = {
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
    }
    return parse_feed(response.content, source), meta


def fetch_github_releases(
    source: SourceSpec,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 30.0,
) -> tuple[list[NewsItem], dict[str, Any]]:
    repo = source.url.rstrip("/").split("github.com/")[-1]
    api_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(api_url, headers=headers, params={"per_page": 10})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(f"unexpected GitHub releases payload for {repo}")

    items: list[NewsItem] = []
    for release in payload:
        if not isinstance(release, dict):
            continue
        title = str(release.get("name") or release.get("tag_name") or "").strip()
        url = str(release.get("html_url") or "").strip()
        if not title or not url:
            continue
        release_id = release.get("id")
        items.append(
            _make_item(
                source,
                title,
                url,
                published_at=_iso(release.get("published_at")),
                guid=str(release_id) if release_id is not None else None,
                summary=_truncate(release.get("body")),
            )
        )
    return items, {}


def item_exists(connection: sqlite3.Connection, item: NewsItem) -> bool:
    """Deterministic dedup: source GUID, then canonical URL, then content hash."""

    if item.guid:
        row = connection.execute(
            "SELECT 1 FROM news_items WHERE source_id = ? AND guid = ?",
            (item.source_id, item.guid),
        ).fetchone()
        if row is not None:
            return True
    row = connection.execute(
        "SELECT 1 FROM news_items WHERE canonical_url = ? OR content_hash = ?",
        (item.canonical_url, item.content_hash),
    ).fetchone()
    return row is not None


def store_items(connection: sqlite3.Connection, items: list[NewsItem]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    fetched_at = _now_iso()
    for item in items:
        if item_exists(connection, item):
            skipped += 1
            continue
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO news_items
                (source_id, guid, title, url, canonical_url, published_at,
                 fetched_at, category, summary, content_hash, processing_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
            """,
            (
                item.source_id,
                item.guid,
                item.title,
                item.url,
                item.canonical_url,
                item.published_at,
                fetched_at,
                item.category,
                item.summary,
                item.content_hash,
            ),
        )
        if cursor.rowcount:
            inserted += 1
        else:
            skipped += 1
    connection.commit()
    return inserted, skipped


def ingest_source(
    connection: sqlite3.Connection,
    source: SourceSpec,
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> IngestionResult:
    """Fetch one source, store new items, and record fetch metadata or errors."""

    db.upsert_source(connection, source)
    state = db.get_source(connection, source.id)

    try:
        if source.type == "rss":
            items, meta = fetch_rss(
                source,
                etag=state["etag"] if state else None,
                last_modified=state["last_modified"] if state else None,
                transport=transport,
            )
        else:
            items, meta = fetch_github_releases(source, token=token, transport=transport)
    except Exception as exc:  # noqa: BLE001 - a bad source must not stop the run
        log.warning("news source %s failed: %s", source.id, exc)
        db.record_source_fetch(connection, source.id, error=True)
        return IngestionResult(
            source.id,
            0,
            0,
            0,
            error=str(exc),
            consecutive_failures=(state["error_count"] if state else 0) + 1,
        )

    if meta.get("not_modified"):
        db.record_source_fetch(connection, source.id, etag=meta.get("etag"))
        return IngestionResult(source.id, 0, 0, 0, not_modified=True)

    inserted, skipped = store_items(connection, items)
    db.record_source_fetch(
        connection, source.id, etag=meta.get("etag"), last_modified=meta.get("last_modified")
    )
    return IngestionResult(source.id, len(items), inserted, skipped)


def ingest_all(
    connection: sqlite3.Connection,
    sources: list[SourceSpec],
    *,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[IngestionResult]:
    return [
        ingest_source(connection, source, token=token, transport=transport)
        for source in sources
        if source.enabled
    ]
