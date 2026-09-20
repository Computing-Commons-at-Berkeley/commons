"""Temporal views over one news corpus (spec section 20).

There is one corpus. 24h, 7d, and 30d are views, not separate pipelines.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from commons.errors import CommonsError

WINDOW_DELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class NewsQueryError(CommonsError):
    """A news query could not be answered."""


def window_since(label: str, *, now: datetime | None = None) -> datetime:
    delta = WINDOW_DELTAS.get(label)
    if delta is None:
        allowed = ", ".join(sorted(WINDOW_DELTAS))
        raise NewsQueryError(f"unknown window {label!r}; expected one of {allowed}")
    moment = now or datetime.now(UTC)
    return moment - delta


def items_since(
    connection: sqlite3.Connection,
    since: datetime,
    *,
    category: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = """
        SELECT * FROM news_items
        WHERE COALESCE(published_at, fetched_at) >= ?
    """
    params: list[Any] = [since.isoformat()]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def items_for_window(
    connection: sqlite3.Connection,
    label: str,
    *,
    now: datetime | None = None,
    category: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return items_since(connection, window_since(label, now=now), category=category, limit=limit)
