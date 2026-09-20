"""Digest artifacts: render, parse, locate, and list.

Digests live at data/digests/<date>-<period>[-<category>].md. The same code path
serves /digest and the scheduled weekly digest (plan section 33).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from commons.community_repo.markdown import (
    NONE_RECORDED,
    parse_frontmatter,
    render_document,
    split_section_list,
)
from commons.community_repo.schemas import DigestArtifact
from commons.errors import ArtifactError
from commons.text import slugify

DIGESTS_DIR = "data/digests"

__all__ = [
    "DIGESTS_DIR",
    "digest_relative_path",
    "digests_dir",
    "existing_digest_names",
    "list_digests",
    "parse_digest_artifact",
    "plan_digest_name",
    "read_digest",
    "render_digest_artifact",
]


def digests_dir(data_root: Path) -> Path:
    return Path(data_root) / "digests"


def digest_relative_path(name: str) -> str:
    return f"{DIGESTS_DIR}/{name}.md"


def existing_digest_names(data_root: Path) -> set[str]:
    directory = digests_dir(data_root)
    if not directory.exists():
        return set()
    return {path.stem for path in directory.glob("*.md")}


def plan_digest_name(period_start: datetime, label: str, *, category: str | None = None) -> str:
    """Deterministic digest file name, for example 2026-09-20-7d."""

    name = f"{period_start.strftime('%Y-%m-%d')}-{label}"
    if category:
        name = f"{name}-{slugify(category)}"
    return name


def render_digest_artifact(artifact: DigestArtifact) -> str:
    frontmatter: dict[str, Any] = {
        "period_start": artifact.period_start,
        "period_end": artifact.period_end,
        "generated_at": artifact.generated_at,
    }
    if artifact.category:
        frontmatter["category"] = artifact.category
    sections = [
        (section.heading, section.body.strip() or NONE_RECORDED) for section in artifact.sections
    ]
    return render_document(frontmatter, sections)


def parse_digest_artifact(text: str) -> DigestArtifact:
    data, body = parse_frontmatter(text)
    payload: dict[str, Any] = dict(data)
    payload["sections"] = [
        {"heading": heading, "body": "" if content == NONE_RECORDED else content}
        for heading, content in split_section_list(body)
    ]
    try:
        return DigestArtifact.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError
        raise ArtifactError(f"artifact does not match the digest schema: {exc}") from exc


def read_digest(path: Path) -> DigestArtifact:
    return parse_digest_artifact(Path(path).read_text(encoding="utf-8"))


def list_digests(data_root: Path) -> list[DigestArtifact]:
    """All digests, newest period first (used by tests and the UI)."""

    directory = digests_dir(data_root)
    if not directory.exists():
        return []
    digests: list[DigestArtifact] = []
    for path in sorted(directory.glob("*.md")):
        try:
            digests.append(read_digest(path))
        except (ArtifactError, OSError):
            continue
    return sorted(digests, key=lambda digest: digest.period_end, reverse=True)
