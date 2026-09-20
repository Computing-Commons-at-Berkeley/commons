"""Digest logic.

One code path serves the manual /digest command and the scheduled weekly digest
(plan section 33). Deterministic candidate construction happens before any LLM
call, and the LLM only synthesizes the candidate set (plan section 32): it does
not crawl or decide community priorities from scratch.

The candidate set deliberately mixes three sources into one digest: member-shared
Discord activity, news items already stored in SQLite, and project records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from commons.community_repo.schemas import DigestSection
from commons.errors import DigestError
from commons.llm import LLMClient
from commons.prompts import DIGEST_SYSTEM_PROMPT, DIGEST_USER_TEMPLATE

PERIOD_DAYS: dict[str, int] = {"1d": 1, "7d": 7, "30d": 30}
DEFAULT_PERIOD = "7d"


@dataclass(frozen=True)
class DigestPeriod:
    label: str
    start: datetime
    end: datetime

    @classmethod
    def from_label(cls, label: str, *, now: datetime | None = None) -> DigestPeriod:
        days = PERIOD_DAYS.get(label)
        if days is None:
            allowed = ", ".join(sorted(PERIOD_DAYS))
            raise DigestError(f"unknown digest period {label!r}; expected one of {allowed}")
        end = now or datetime.now(UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return cls(label=label, start=end - timedelta(days=days), end=end)


@dataclass(frozen=True)
class DigestMessage:
    channel: str
    author: str
    content: str
    created_at: str | None = None
    jump_url: str | None = None


@dataclass(frozen=True)
class ChannelActivity:
    channel: str
    messages: list[DigestMessage] = field(default_factory=list)


@dataclass(frozen=True)
class NewsCandidate:
    title: str
    url: str
    category: str
    published_at: str | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class ProjectCandidate:
    title: str
    status: str
    goal: str = ""
    current_state: str = ""
    relative_path: str | None = None


@dataclass(frozen=True)
class RadarCandidate:
    repo: str
    title: str
    url: str
    kind: str = "issue"
    labels: list[str] = field(default_factory=list)


def _fit_blocks(blocks: list[str], max_chars: int) -> str:
    """Bound the whole candidate text while giving every source a share (R14).

    Truncating the concatenation would let an early Discord block consume the
    entire budget and drop news, projects or radar entirely. Each block is
    trimmed to an equal share first, so no source class disappears because
    another was verbose.
    """

    if not blocks:
        return ""
    if sum(len(block) for block in blocks) <= max_chars:
        return "\n\n".join(blocks)

    share = max(200, max_chars // len(blocks))
    trimmed: list[str] = []
    for block in blocks:
        if len(block) <= share:
            trimmed.append(block)
        else:
            trimmed.append(block[:share].rstrip() + "\n[truncated]")
    text = "\n\n".join(trimmed)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[candidates truncated]"
    return text


def build_candidate_text(
    activity: list[ChannelActivity],
    *,
    news: list[NewsCandidate] | None = None,
    projects: list[ProjectCandidate] | None = None,
    radar: list[RadarCandidate] | None = None,
    max_chars: int = 12000,
    max_per_channel: int = 40,
    max_news: int = 40,
) -> str:
    """Deterministic candidate text. No LLM involvement before this point."""

    blocks: list[str] = []

    for group in activity:
        lines: list[str] = []
        for message in group.messages[:max_per_channel]:
            content = (message.content or "").strip()
            if not content:
                continue
            stamp = f" ({message.created_at})" if message.created_at else ""
            link = f" [link]({message.jump_url})" if message.jump_url else ""
            lines.append(f"{message.author}{stamp}: {content}{link}")
        if lines:
            blocks.append(f"## #{group.channel}\n" + "\n".join(lines))

    by_category: dict[str, list[NewsCandidate]] = {}
    for item in (news or [])[:max_news]:
        by_category.setdefault(item.category, []).append(item)
    for category in sorted(by_category):
        lines = [f"- [{item.title}]({item.url})" for item in by_category[category]]
        blocks.append(f"## News: {category}\n" + "\n".join(lines))

    if projects:
        lines = []
        for project in projects:
            detail = project.goal or project.current_state
            suffix = f" - {detail}" if detail else ""
            lines.append(f"- {project.title} (status: {project.status}){suffix}")
        blocks.append("## Projects\n" + "\n".join(lines))

    if radar:
        lines = []
        for entry in radar:
            labels = f" (labels: {', '.join(entry.labels)})" if entry.labels else ""
            lines.append(f"- {entry.repo} [{entry.kind}] {entry.title}{labels} - {entry.url}")
        blocks.append("## OSS Radar\n" + "\n".join(lines))

    return _fit_blocks(blocks, max_chars)


def generate_digest(
    client: LLMClient,
    *,
    period: DigestPeriod,
    candidate_text: str,
    category: str | None = None,
) -> list[DigestSection]:
    """Synthesize digest sections from already-selected candidates."""

    scope = f" for category {category}" if category else ""
    user = DIGEST_USER_TEMPLATE.format(
        period=period.label,
        scope=scope,
        candidates=candidate_text or "(no candidate material)",
    )
    data = client.complete_json(operation="digest", system=DIGEST_SYSTEM_PROMPT, user=user)

    sections: list[DigestSection] = []
    raw = data.get("sections")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            heading = str(item.get("heading") or "").strip()
            body = str(item.get("body") or "").strip()
            if heading and body:
                sections.append(DigestSection(heading=heading, body=body))
    if not sections:
        raise DigestError("digest synthesis produced no usable sections")
    return sections
