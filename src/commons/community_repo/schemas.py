"""Durable artifact schemas.

Markdown with YAML frontmatter is the on-disk format (plan sections 13-14).
These models define the in-memory shape; rendering and parsing live in
artifacts.py and projects.py.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

ProjectStatus = Literal["active", "paused", "archived"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class DiscordSource(BaseModel):
    """Provenance back to Discord.

    Field names for the three identifiers required by the spec are kept exactly
    as documented (discord_channel_id / discord_message_id / discord_thread_id).
    """

    model_config = ConfigDict(extra="forbid")

    guild_id: int | None = None
    discord_channel_id: int | None = None
    discord_channel_name: str | None = None
    discord_message_id: int | None = None
    discord_thread_id: int | None = None
    discord_message_url: str | None = None
    discord_author: str | None = None

    def identity_keys(self) -> list[str]:
        """Stable keys used for idempotency checks."""

        keys: list[str] = []
        if self.discord_thread_id is not None:
            keys.append(f"thread:{self.discord_thread_id}")
        if self.discord_message_id is not None:
            keys.append(f"message:{self.discord_message_id}")
        return keys


class ArchiveDraft(BaseModel):
    """Structured LLM output for one archived discussion."""

    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class KnowledgeArtifact(BaseModel):
    """A durable knowledge note, ready to render to Markdown."""

    model_config = ConfigDict(extra="forbid")

    title: str
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str
    tags: list[str] = Field(default_factory=list)
    source: DiscordSource
    summary: str
    key_points: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)

    @classmethod
    def from_draft(
        cls,
        draft: ArchiveDraft,
        *,
        source: DiscordSource,
        created_by: str,
        created_at: datetime | None = None,
    ) -> KnowledgeArtifact:
        return cls(
            title=draft.title.strip(),
            created_at=created_at or utcnow(),
            created_by=created_by,
            tags=list(draft.tags),
            source=source,
            summary=draft.summary.strip(),
            key_points=list(draft.key_points),
            open_questions=list(draft.open_questions),
            references=list(draft.references),
        )


class ProjectArtifact(BaseModel):
    """A lightweight project record (spec section 8, plan section 14).

    v0.1 deliberately keeps this small: no lifecycle machinery, no task system.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    status: ProjectStatus = "active"
    members: list[str] = Field(default_factory=list)
    discord_thread_id: int | None = None
    repo: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    goal: str = ""
    current_state: str = ""
    resources: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("project title must not be empty")
        return value

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _REPO_RE.fullmatch(value):
            raise ValueError(f"repo must look like owner/name, got {value!r}")
        return value
