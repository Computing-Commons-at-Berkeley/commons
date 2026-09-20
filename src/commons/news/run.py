"""Wire the news pipeline to settings: open the runtime DB, load sources, ingest.

This is the function the scheduler calls. It keeps the module boundaries thin:
settings and YAML loading live outside the ingestion code.
"""

from __future__ import annotations

import httpx

from commons.config import load_sources_config
from commons.logging import get_logger
from commons.news import db
from commons.news.ingest import IngestionResult, ingest_all
from commons.settings import Settings

log = get_logger(__name__)


def run_ingestion(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    token: str | None = None,
) -> list[IngestionResult]:
    """Ingest every enabled configured source once."""

    repo_path = settings.require_community_repo_path()
    sources = load_sources_config(repo_path / "config" / "sources.yaml")

    if token is None and settings.github_token is not None:
        token = settings.github_token.get_secret_value()

    connection = db.connect(settings.news_db_path)
    try:
        db.init_db(connection)
        results = ingest_all(connection, sources.sources, token=token, transport=transport)
    finally:
        connection.close()

    inserted = sum(result.inserted for result in results)
    errors = [result.source_id for result in results if result.error]
    log.info("news ingestion: %d item(s) inserted, %d source(s) errored", inserted, len(errors))
    return results
