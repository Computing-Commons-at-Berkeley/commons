"""Shared Markdown-with-YAML-frontmatter helpers.

Two durable artifact types now exist (knowledge notes and project records), so
frontmatter and section handling lives in one place instead of being duplicated.
The artifact modules own their own schemas and paths; this module only knows how
to turn a mapping plus body sections into text and back.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from commons.errors import ArtifactError

FENCE = "---"
NONE_RECORDED = "_(none recorded)_"
_HEADING_RE = re.compile(r"^#\s+(.*)$")


def render_document(frontmatter: dict[str, Any], sections: list[tuple[str, str]]) -> str:
    """Render frontmatter plus ordered sections as a Markdown document."""

    parts: list[str] = [
        FENCE,
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip(),
        FENCE,
        "",
    ]
    for heading, content in sections:
        parts.extend([f"# {heading}", "", content, ""])
    return "\n".join(parts).rstrip() + "\n"


def render_bullets(items: list[str]) -> str:
    rendered = [f"- {item.strip()}" for item in items if item and item.strip()]
    return "\n".join(rendered) if rendered else NONE_RECORDED


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a document into (frontmatter mapping, body)."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        raise ArtifactError("artifact is missing YAML frontmatter")
    end: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == FENCE:
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


def split_sections(body: str) -> dict[str, str]:
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


def parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value != NONE_RECORDED:
                items.append(value)
    return items


def parse_section_text(text: str) -> str:
    """Return prose for a section, mapping the empty placeholder back to ''."""

    stripped = text.strip()
    return "" if stripped == NONE_RECORDED else stripped
