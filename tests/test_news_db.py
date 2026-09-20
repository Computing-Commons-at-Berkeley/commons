from __future__ import annotations

from pathlib import Path

from commons.config import SourceSpec
from commons.news import db


def make_source(**overrides: object) -> SourceSpec:
    data: dict[str, object] = {
        "id": "example",
        "type": "rss",
        "url": "https://example.com/feed.xml",
        "category": "ml",
    }
    data.update(overrides)
    return SourceSpec.model_validate(data)


def test_init_upsert_and_fetch_state(tmp_path: Path) -> None:
    connection = db.connect(tmp_path / "news.db")
    db.init_db(connection)

    db.upsert_source(connection, make_source())
    row = db.get_source(connection, "example")
    assert row is not None
    assert row["type"] == "rss"

    db.upsert_source(connection, make_source(category="infra"))
    assert db.get_source(connection, "example")["category"] == "infra"

    db.record_source_fetch(connection, "example", etag="abc")
    row = db.get_source(connection, "example")
    assert row["etag"] == "abc"
    assert row["error_count"] == 0

    db.record_source_fetch(connection, "example", error=True)
    assert db.get_source(connection, "example")["error_count"] == 1

    # A later success resets the error count.
    db.record_source_fetch(connection, "example")
    assert db.get_source(connection, "example")["error_count"] == 0
