"""The /archive workflow: Discord discussion -> durable Markdown -> Git.

This module is discord-free on purpose. Discord-specific code lives in
commands.py and bot.py and only translates Discord objects into the small DTOs
defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from commons.community_repo.artifacts import (
    find_artifact_by_source,
    knowledge_relative_path,
    parse_frontmatter,
    plan_slug,
    render_knowledge_artifact,
)
from commons.community_repo.git import CommunityRepo
from commons.community_repo.schemas import DiscordSource, KnowledgeArtifact
from commons.errors import ArchiveError, ArtifactError
from commons.llm import LLMClient, summarize_archive

DEFAULT_MAX_CONTEXT_MESSAGES = 100
DEFAULT_MAX_ARTICLE_CHARS = 12000


@dataclass(frozen=True)
class TranscriptMessage:
    author: str
    content: str
    created_at: str | None = None


@dataclass(frozen=True)
class ArchiveRequest:
    source: DiscordSource
    messages: list[TranscriptMessage] = field(default_factory=list)
    requested_by: str = "unknown"
    title_hint: str = ""
    channel_name: str = ""


@dataclass(frozen=True)
class ArchiveOutcome:
    title: str
    relative_path: str
    created: bool
    commit_sha: str | None
    detail: str = ""


def render_transcript(
    messages: list[TranscriptMessage],
    *,
    max_chars: int = DEFAULT_MAX_ARTICLE_CHARS,
    max_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
) -> str:
    lines: list[str] = []
    for message in messages[:max_messages]:
        content = (message.content or "").strip()
        if not content:
            continue
        stamp = f" ({message.created_at})" if message.created_at else ""
        lines.append(f"{message.author}{stamp}: {content}")
    transcript = "\n\n".join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n\n[transcript truncated]"
    return transcript


def _relative_to(repo_path: Path, path: Path) -> str:
    return path.relative_to(repo_path).as_posix()


class ArchiveService:
    """Idempotent, provenance-preserving archive writer."""

    def __init__(
        self,
        repo: CommunityRepo,
        llm: LLMClient,
        *,
        max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
        max_article_chars: int = DEFAULT_MAX_ARTICLE_CHARS,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.max_context_messages = max_context_messages
        self.max_article_chars = max_article_chars

    @property
    def data_root(self) -> Path:
        return self.repo.path / "data"

    def archive(self, request: ArchiveRequest) -> ArchiveOutcome:
        existing = find_artifact_by_source(self.data_root, request.source)
        if existing is not None:
            return ArchiveOutcome(
                title=_read_title(existing),
                relative_path=_relative_to(self.repo.path, existing),
                created=False,
                commit_sha=None,
                detail=(
                    "an artifact already references this Discord source; "
                    "returning the existing note instead of creating a duplicate"
                ),
            )

        transcript = render_transcript(
            request.messages,
            max_chars=self.max_article_chars,
            max_messages=self.max_context_messages,
        )
        if not transcript.strip():
            raise ArchiveError("no readable messages were found to archive")

        draft = summarize_archive(
            self.llm,
            requested_by=request.requested_by,
            channel=request.channel_name,
            title_hint=request.title_hint,
            transcript=transcript,
        )
        artifact = KnowledgeArtifact.from_draft(
            draft,
            source=request.source,
            created_by=request.requested_by,
        )
        slug = plan_slug(self.data_root, artifact.title)
        relative_path = knowledge_relative_path(slug)
        content = render_knowledge_artifact(artifact)

        result = self.repo.write_artifact(
            relative_path,
            content,
            commit_message=f"archive: add note on {artifact.title}",
        )
        return ArchiveOutcome(
            title=artifact.title,
            relative_path=relative_path,
            created=True,
            commit_sha=result.commit_sha,
            detail=result.detail,
        )


def _read_title(path: Path) -> str:
    try:
        data, _body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (ArtifactError, OSError):
        return path.stem
    return str(data.get("title") or path.stem)
