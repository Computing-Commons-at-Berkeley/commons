from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from commons.community_repo.artifacts import render_knowledge_artifact
from commons.community_repo.digests import render_digest_artifact
from commons.community_repo.schemas import (
    DigestArtifact,
    DigestSection,
    DiscordSource,
    KnowledgeArtifact,
)
from commons.discord.project import ProjectCreateRequest, ProjectService
from commons.news import db as news_db
from commons.web import data
from fakes import FakeRepo


def seed(tmp_path: Path) -> tuple[Path, Path]:
    repo = FakeRepo(tmp_path)
    data_root = tmp_path / "data"
    for name in ("knowledge", "digests", "resources"):
        (data_root / name).mkdir(parents=True, exist_ok=True)

    artifact = KnowledgeArtifact(
        title="Scheduling batching notes",
        created_by="alice",
        source=DiscordSource(discord_message_id=1),
        summary="Batching policy affects tail latency.",
    )
    (data_root / "knowledge" / "scheduling-batching-notes.md").write_text(
        render_knowledge_artifact(artifact), encoding="utf-8"
    )

    digest = DigestArtifact(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        sections=[DigestSection(heading="ML Research", body="- a paper")],
    )
    (data_root / "digests" / "2026-01-01-7d.md").write_text(
        render_digest_artifact(digest), encoding="utf-8"
    )

    (data_root / "resources" / "reading-list.md").write_text("# Reading list\n", encoding="utf-8")

    ProjectService(repo).create(ProjectCreateRequest(name="Alpha Project"))

    db_path = tmp_path / "news.db"
    connection = news_db.connect(db_path)
    news_db.init_db(connection)
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        INSERT INTO news_items
            (source_id, title, url, canonical_url, published_at, fetched_at,
             category, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s", "A batching paper", "https://e.test/p", "https://e.test/p", now, now, "ml", "h1"),
    )
    connection.commit()
    connection.close()
    return data_root, db_path


def test_reads_artifacts(tmp_path: Path) -> None:
    data_root, _db = seed(tmp_path)

    assert [item.title for item in data.knowledge_artifacts(data_root)] == [
        "Scheduling batching notes"
    ]
    assert [project.title for project in data.projects(data_root)] == ["Alpha Project"]
    assert [path.name for path in data.resources(data_root)] == ["reading-list.md"]

    latest = data.latest_digest(data_root)
    assert latest is not None
    assert latest.sections[0].heading == "ML Research"


def test_news_items_window(tmp_path: Path) -> None:
    data_root, db_path = seed(tmp_path)
    rows = data.news_items(db_path, "7d")
    assert [row["title"] for row in rows] == ["A batching paper"]


def test_news_items_respects_old_items(tmp_path: Path) -> None:
    _data_root, db_path = seed(tmp_path)
    connection = news_db.connect(db_path)
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    connection.execute(
        """
        INSERT INTO news_items
            (source_id, title, url, canonical_url, published_at, fetched_at,
             category, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("s", "Old news", "https://e.test/old", "https://e.test/old", old, old, "ml", "h2"),
    )
    connection.commit()
    connection.close()

    titles = [row["title"] for row in data.news_items(db_path, "7d")]
    assert titles == ["A batching paper"]


def test_search_across_artifacts_and_news(tmp_path: Path) -> None:
    data_root, db_path = seed(tmp_path)

    hits = data.search(data_root, db_path, "batching")
    kinds = {hit.kind for hit in hits}
    assert "knowledge" in kinds
    assert "news" in kinds

    assert data.search(data_root, db_path, "   ") == []
    assert data.search(data_root, db_path, "nothing-matches-this") == []


def test_watch_state_is_empty_without_data(tmp_path: Path) -> None:
    _data_root, db_path = seed(tmp_path)
    assert data.watch_state(db_path) == []


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "news.db"
    data_root = tmp_path / "data"

    assert data.news_items(db_path) == []
    assert data.watch_state(db_path) == []
    assert data.search(data_root, db_path, "anything") == []
    assert not db_path.exists()
