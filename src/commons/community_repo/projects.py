"""Project records: render, parse, locate, and list.

Project records live at data/projects/<slug>.md and stay deliberately small
(spec section 8, plan section 14). Status is one of active | paused | archived.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from commons.community_repo.markdown import (
    NONE_RECORDED,
    parse_bullets,
    parse_frontmatter,
    parse_section_text,
    render_bullets,
    render_document,
    split_sections,
)
from commons.community_repo.schemas import ProjectArtifact
from commons.errors import ArtifactError
from commons.text import slugify, unique_slug

PROJECTS_DIR = "data/projects"

__all__ = [
    "PROJECTS_DIR",
    "existing_project_slugs",
    "find_project_by_thread",
    "find_project_path",
    "list_projects",
    "parse_project_artifact",
    "plan_project_slug",
    "project_relative_path",
    "projects_dir",
    "read_project",
    "render_project_artifact",
]


def projects_dir(data_root: Path) -> Path:
    return Path(data_root) / "projects"


def project_relative_path(slug: str) -> str:
    return f"{PROJECTS_DIR}/{slug}.md"


def existing_project_slugs(data_root: Path) -> set[str]:
    directory = projects_dir(data_root)
    if not directory.exists():
        return set()
    return {path.stem for path in directory.glob("*.md")}


def plan_project_slug(data_root: Path, title: str) -> str:
    """Collision-free slug, used when creating a project with a new name."""

    return unique_slug(slugify(title), existing_project_slugs(data_root))


def render_project_artifact(project: ProjectArtifact) -> str:
    frontmatter = {
        "title": project.title,
        "status": project.status,
        "members": list(project.members),
        "discord_thread_id": project.discord_thread_id,
        "repo": project.repo,
        "created_at": project.created_at,
    }
    sections = [
        ("Goal", project.goal.strip() or NONE_RECORDED),
        ("Current State", project.current_state.strip() or NONE_RECORDED),
        ("Relevant Resources", render_bullets(project.resources)),
        ("Next Actions", render_bullets(project.next_actions)),
    ]
    return render_document(frontmatter, sections)


def parse_project_artifact(text: str) -> ProjectArtifact:
    data, body = parse_frontmatter(text)
    sections = split_sections(body)
    payload: dict[str, Any] = dict(data)
    payload["goal"] = parse_section_text(sections.get("goal", ""))
    payload["current_state"] = parse_section_text(sections.get("current state", ""))
    payload["resources"] = parse_bullets(sections.get("relevant resources", ""))
    payload["next_actions"] = parse_bullets(sections.get("next actions", ""))
    try:
        return ProjectArtifact.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise ArtifactError(f"artifact does not match the project schema: {exc}") from exc


def read_project(path: Path) -> ProjectArtifact:
    return parse_project_artifact(Path(path).read_text(encoding="utf-8"))


def list_projects(data_root: Path) -> list[ProjectArtifact]:
    """All project records, sorted by title (used by tests and the UI)."""

    directory = projects_dir(data_root)
    if not directory.exists():
        return []
    projects: list[ProjectArtifact] = []
    for path in sorted(directory.glob("*.md")):
        try:
            projects.append(read_project(path))
        except (ArtifactError, OSError):
            continue
    return sorted(projects, key=lambda project: project.title.lower())


def find_project_path(data_root: Path, slug: str) -> Path | None:
    path = projects_dir(data_root) / f"{slug}.md"
    return path if path.exists() else None


def find_project_by_thread(data_root: Path, thread_id: int) -> Path | None:
    """Idempotency by Discord thread: one project record per linked thread."""

    directory = projects_dir(data_root)
    if not directory.exists():
        return None
    for path in sorted(directory.glob("*.md")):
        try:
            data, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ArtifactError, OSError):
            continue
        if data.get("discord_thread_id") == thread_id:
            return path
    return None
