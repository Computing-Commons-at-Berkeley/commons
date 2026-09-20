"""Render, parse, and locate durable Markdown artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from commons.community_repo.schemas import DiscordSource, KnowledgeArtifact
from commons.errors import ArtifactError
from commons.text import slugify, unique_slug

KNOWLEDGE_DIR = "data/knowledge"
_FENCE = "---"
_NONE_RECORDED = "_(none recorded)_"


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


def _render_bullets(items: list[str]) -> str:
    rendered = [f"- {item.strip()}" for item in items if item and item.strip()]
    return "\n".join(rendered) if rendered else _NONE_RECORDED


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
        ("Summary", artifact.summary.strip() or _NONE_RECORDED),
        ("Key Points", _render_bullets(artifact.key_points)),
        ("Open Questions", _render_bullets(artifact.open_questions)),
        ("References", _render_bullets(artifact.references)),
    ]

    parts: list[str] = [
        _FENCE,
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
        _FENCE,
        "",
    ]
    for heading, content in sections:
        parts.extend([f"# {heading}", "", content, ""])
    return "\n".join(parts).rstrip() + "\n"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split an artifact into (frontmatter mapping, body)."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise ArtifactError("artifact is missing YAML frontmatter")
    end: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == _FENCE:
            end = index
            break
    if end is None:
        raise ArtifactError("artifact frontmatter is not terminated")
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        raise ArtifactError(f"invalid artifact frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactError("artifact frontmatter must be a mapping")
    body = "\n".join(lines[end + 1 :]).strip()
    return data, body


_HEADING_RE = re.compile(r"^#\s+(.*)$")


def _split_sections(body: str) -> dict[str, str]:
    """Split a Markdown body into {lowercased heading: text}."""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            current = match.group(1).strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value != _NONE_RECORDED:
                items.append(value)
    return items


def parse_knowledge_artifact(text: str) -> KnowledgeArtifact:
    """Parse Markdown back into a KnowledgeArtifact (used by tests and the UI).

    Metadata and provenance come from the YAML frontmatter; the narrative
    sections come from the Markdown body, exactly as rendered.
    """

    data, body = parse_frontmatter(text)
    sections = _split_sections(body)
    payload: dict[str, Any] = dict(data)
    payload["summary"] = sections.get("summary", "")
    payload["key_points"] = _parse_bullets(sections.get("key points", ""))
    payload["open_questions"] = _parse_bullets(sections.get("open questions", ""))
    payload["references"] = _parse_bullets(sections.get("references", ""))
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
