"""Wire the Berkeley/OSS radar to settings: load watchlists, collect, track state."""

from __future__ import annotations

from datetime import datetime

import httpx

from commons.config import load_watchlist_config
from commons.github.watchlist import RadarItem, collect_radar
from commons.news import db
from commons.settings import Settings


def collect_radar_from_settings(
    settings: Settings,
    *,
    since: datetime,
    now: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[RadarItem]:
    watchlists = load_watchlist_config(
        settings.require_community_repo_path() / "config" / "watchlists.yaml"
    )
    token = settings.github_token.get_secret_value() if settings.github_token else None

    connection = db.connect(settings.news_db_path)
    try:
        db.init_db(connection)
        return collect_radar(
            watchlists.repositories,
            connection=connection,
            since=since,
            now=now,
            token=token,
            transport=transport,
        )
    finally:
        connection.close()
