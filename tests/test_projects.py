from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from commons.community_repo.projects import (
    find_project_by_thread,
    list_projects,
    parse_project_artifact,
    plan_project_slug,
    project_relative_path,
    render_project_artifact,
)
from commons.community_repo.schemas import ProjectArtifact
from commons.discord.project import ProjectCreateRequest, ProjectService
from commons.errors import ArtifactError, ProjectError
from fakes import FakeRepo


def make_project() -> ProjectArtifact:
    return ProjectArtifact(
        title="SGLang starter contribution",
        status="active",
        members=["alice", "bob"],
        discord_thread_id=555,
        repo="sgl-project/sglang",
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        goal="Land one starter contribution.",
        current_state="Reading the issue tracker.",
        resources=["https://example.test/issue/1"],
        next_actions=["Pick an issue", "Open a draft PR"],
    )


def test_render_parse_round_trip() -> None:
    text = render_project_artifact(make_project())
    assert text.startswith("---")
    parsed = parse_project_artifact(text)
    assert parsed.title == "SGLang starter contribution"
    assert parsed.status == "active"
    assert parsed.members == ["alice", "bob"]
    assert parsed.discord_thread_id == 555
    assert parsed.repo == "sgl-project/sglang"
    assert parsed.goal == "Land one starter contribution."
    assert parsed.next_actions == ["Pick an issue", "Open a draft PR"]


def test_parse_handles_empty_sections() -> None:
    project = make_project()
    project.goal = ""
    project.resources = []
    parsed = parse_project_artifact(render_project_artifact(project))
    assert parsed.goal == ""
    assert parsed.resources == []


def test_project_relative_path() -> None:
    assert project_relative_path("my-project") == "data/projects/my-project.md"


def test_status_must_be_known() -> None:
    with pytest.raises(ValidationError):
        ProjectArtifact(title="x", status="blocked")  # type: ignore[arg-type]


def test_plan_project_slug_avoids_collisions(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    (data_root / "projects").mkdir(parents=True)
    (data_root / "projects" / "alpha.md").write_text("x", encoding="utf-8")
    assert plan_project_slug(data_root, "Alpha") == "alpha-2"


def test_service_create_writes_record_and_commit(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ProjectService(repo)

    outcome = service.create(
        ProjectCreateRequest(
            name="SGLang starter contribution",
            goal="Land one starter contribution.",
            members=["alice"],
            discord_thread_id=555,
        )
    )

    assert outcome.created is True
    assert outcome.relative_path == "data/projects/sglang-starter-contribution.md"
    assert outcome.status == "active"
    assert repo.commits == ["project: create sglang-starter-contribution project"]

    parsed = parse_project_artifact((repo.path / outcome.relative_path).read_text(encoding="utf-8"))
    assert parsed.discord_thread_id == 555
    assert parsed.members == ["alice"]


def test_service_create_is_idempotent_for_the_same_thread(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ProjectService(repo)
    request = ProjectCreateRequest(name="Alpha", members=["alice"], discord_thread_id=7)

    first = service.create(request)
    second = service.create(request)

    assert first.created is True
    assert second.created is False
    assert second.relative_path == first.relative_path
    assert repo.commits == ["project: create alpha project"]


def test_service_create_returns_existing_for_duplicate_name(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ProjectService(repo)

    first = service.create(ProjectCreateRequest(name="Alpha", discord_thread_id=1))
    second = service.create(ProjectCreateRequest(name="Alpha", discord_thread_id=2))

    assert first.created is True
    assert second.created is False
    assert second.relative_path == first.relative_path
    assert "already exists" in second.detail
    assert len(repo.commits) == 1


def test_service_set_status_updates_record(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ProjectService(repo)
    service.create(ProjectCreateRequest(name="Alpha"))

    outcome = service.set_status("alpha", "paused")

    assert outcome.status == "paused"
    parsed = parse_project_artifact((repo.path / outcome.relative_path).read_text(encoding="utf-8"))
    assert parsed.status == "paused"
    assert repo.commits[-1] == "project: set alpha status to paused"


def test_service_set_status_missing_project(tmp_path: Path) -> None:
    service = ProjectService(FakeRepo(tmp_path / "community"))
    with pytest.raises(ProjectError):
        service.set_status("missing", "archived")


def test_service_rejects_empty_name(tmp_path: Path) -> None:
    service = ProjectService(FakeRepo(tmp_path / "community"))
    with pytest.raises(ProjectError):
        service.create(ProjectCreateRequest(name="   "))


def test_find_project_by_thread_and_listing(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ProjectService(repo)
    service.create(ProjectCreateRequest(name="Beta", discord_thread_id=11))
    service.create(ProjectCreateRequest(name="Alpha", discord_thread_id=22))

    data_root = repo.path / "data"
    assert find_project_by_thread(data_root, 22) is not None
    assert find_project_by_thread(data_root, 999) is None
    assert [project.title for project in list_projects(data_root)] == ["Alpha", "Beta"]
    assert [outcome.title for outcome in service.list()] == ["Alpha", "Beta"]


def test_parse_rejects_missing_frontmatter() -> None:
    with pytest.raises(ArtifactError):
        parse_project_artifact("no frontmatter here")
