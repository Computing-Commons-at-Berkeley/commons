"""Durable artifact schemas.

Markdown with YAML frontmatter is the on-disk format (plan section 13). These
models define the in-memory shape; rendering and parsing live in artifacts.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


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
