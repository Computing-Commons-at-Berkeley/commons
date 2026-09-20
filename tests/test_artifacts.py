from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from commons.community_repo.artifacts import (
    find_artifact_by_source,
    knowledge_relative_path,
    parse_knowledge_artifact,
    plan_slug,
    render_knowledge_artifact,
)
from commons.community_repo.schemas import DiscordSource, KnowledgeArtifact


def make_artifact() -> KnowledgeArtifact:
    return KnowledgeArtifact(
        title="SGLang scheduling notes",
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        created_by="alice",
        tags=["infra", "ml"],
        source=DiscordSource(
            guild_id=1,
            discord_channel_id=2,
            discord_message_id=3,
            discord_thread_id=4,
        ),
        summary="Discussed batching policy.",
        key_points=["tail latency"],
        open_questions=["safe configuration?"],
        references=["https://example.test/x"],
    )


def test_render_parse_round_trip() -> None:
    artifact = make_artifact()
    text = render_knowledge_artifact(artifact)
    assert text.startswith("---")
    parsed = parse_knowledge_artifact(text)
    assert parsed.title == artifact.title
    assert parsed.source.discord_thread_id == 4
    assert parsed.tags == ["infra", "ml"]
    assert parsed.key_points == ["tail latency"]
    assert "# Summary" in text


def test_render_handles_empty_sections() -> None:
    artifact = make_artifact()
    artifact.open_questions = []
    text = render_knowledge_artifact(artifact)
    assert "_(none recorded)_" in text


def test_knowledge_relative_path() -> None:
    assert knowledge_relative_path("my-note") == "data/knowledge/my-note.md"


def test_find_artifact_by_source(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "knowledge").mkdir(parents=True)
    path = data_root / "knowledge" / "note.md"
    path.write_text(render_knowledge_artifact(make_artifact()), encoding="utf-8")

    assert find_artifact_by_source(data_root, DiscordSource(discord_thread_id=4)) == path
    assert find_artifact_by_source(data_root, DiscordSource(discord_thread_id=999)) is None
    assert find_artifact_by_source(data_root, DiscordSource()) is None


def test_plan_slug_avoids_collisions(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "knowledge").mkdir(parents=True)
    (data_root / "knowledge" / "my-note.md").write_text("x", encoding="utf-8")
    assert plan_slug(data_root, "My Note") == "my-note-2"
