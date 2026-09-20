"""Knowledge artifacts: render, parse, and locate durable notes."""

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
from commons.community_repo.schemas import DiscordSource, KnowledgeArtifact
from commons.errors import ArtifactError
from commons.text import slugify, unique_slug

KNOWLEDGE_DIR = "data/knowledge"

__all__ = [
    "KNOWLEDGE_DIR",
    "existing_knowledge_slugs",
    "find_artifact_by_source",
    "knowledge_dir",
    "knowledge_relative_path",
    "parse_frontmatter",
    "parse_knowledge_artifact",
    "plan_slug",
    "render_knowledge_artifact",
]


def knowledge_dir(data_root: Path) -> Path:
    return Path(data_root) / "knowledge"


def knowledge_relative_path(slug: str) -> str:
    """Path relative to the community repository root (forward slashes)."""

    return f"{KNOWLEDGE_DIR}/{slug}.md"


def existing_knowledge_slugs(data_root: Path) -> set[str]:
    directory = knowledge_dir(data_root)
    if not directory.exists():
        return set()
    return {path.stem for path in directory.glob("*.md")}


def plan_slug(data_root: Path, title: str) -> str:
    """Deterministic, collision-free slug for a new knowledge artifact."""

    return unique_slug(slugify(title), existing_knowledge_slugs(data_root))


def render_knowledge_artifact(artifact: KnowledgeArtifact) -> str:
    """Render a KnowledgeArtifact to Markdown with YAML frontmatter."""

    frontmatter = {
        "title": artifact.title,
        "created_at": artifact.created_at,
        "created_by": artifact.created_by,
        "tags": list(artifact.tags),
        "source": artifact.source.model_dump(exclude_none=True),
    }
    sections = [
        ("Summary", artifact.summary.strip() or NONE_RECORDED),
        ("Key Points", render_bullets(artifact.key_points)),
        ("Open Questions", render_bullets(artifact.open_questions)),
        ("References", render_bullets(artifact.references)),
    ]
    return render_document(frontmatter, sections)


def parse_knowledge_artifact(text: str) -> KnowledgeArtifact:
    """Parse Markdown back into a KnowledgeArtifact (used by tests and the UI).

    Metadata and provenance come from the YAML frontmatter; the narrative
    sections come from the Markdown body, exactly as rendered.
    """

    data, body = parse_frontmatter(text)
    sections = split_sections(body)
    payload: dict[str, Any] = dict(data)
    payload["summary"] = parse_section_text(sections.get("summary", ""))
    payload["key_points"] = parse_bullets(sections.get("key points", ""))
    payload["open_questions"] = parse_bullets(sections.get("open questions", ""))
    payload["references"] = parse_bullets(sections.get("references", ""))
    try:
        return KnowledgeArtifact.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise ArtifactError(f"artifact does not match the knowledge schema: {exc}") from exc


def find_artifact_by_source(data_root: Path, source: DiscordSource) -> Path | None:
    """Return the existing artifact for a Discord source, if one exists.

    This is the idempotency check: re-archiving the same message or thread must
    return the existing artifact instead of silently duplicating it.
    """

    directory = knowledge_dir(data_root)
    if not directory.exists():
        return None
    wanted = set(source.identity_keys())
    if not wanted:
        return None
    known_fields = set(DiscordSource.model_fields)
    for path in sorted(directory.glob("*.md")):
        try:
            data, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except (ArtifactError, OSError):
            continue
        source_data = data.get("source")
        if not isinstance(source_data, dict):
            continue
        candidate = DiscordSource(**{k: v for k, v in source_data.items() if k in known_fields})
        if wanted & set(candidate.identity_keys()):
            return path
    return None
