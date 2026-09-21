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

# A digest is much longer than a single archive note: several headed sections with
# bullets. 1200 tokens truncates it mid-JSON, so the digest gets its own budget.
DIGEST_MAX_TOKENS = 4000


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
    if sum(len(block) for block in blocks) + 2 * (len(blocks) - 1) <= max_chars:
        return "\n\n".join(blocks)

    share = max(0, (max_chars - 2 * (len(blocks) - 1)) // len(blocks))
    trimmed: list[str] = []
    for block in blocks:
        if len(block) <= share:
            trimmed.append(block)
        else:
            marker = "\n[truncated]"
            trimmed.append((block[: max(0, share - len(marker))].rstrip() + marker)[:share])
    text = "\n\n".join(trimmed)
    return text[:max_chars]


def select_messages(messages: list[DigestMessage], limit: int) -> list[DigestMessage]:
    """Reserve space for each discussion, selecting recent messages before rendering."""
    by_discussion: dict[str, list[DigestMessage]] = {}
    for message in messages:
        if message.content.strip():
            by_discussion.setdefault(message.channel, []).append(message)
    streams = [
        sorted(items, key=lambda item: item.created_at or "", reverse=True)
        for items in by_discussion.values()
    ]
    streams.sort(key=lambda items: items[0].created_at or "", reverse=True)
    chosen: list[DigestMessage] = []
    while streams and len(chosen) < limit:
        for items in streams:
            if len(chosen) >= limit:
                break
            chosen.append(items.pop(0))
        streams = [items for items in streams if items]
    # Preserve the fair, recent-first selection order under the character cap.
    return chosen


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
        for message in select_messages(group.messages, max_per_channel):
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
            details = []
            if project.goal:
                details.append(f"Goal: {project.goal[:1000]}")
            if project.current_state:
                details.append(f"Current state: {project.current_state[:1000]}")
            suffix = " - " + "; ".join(details) if details else ""
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
    max_tokens: int = DIGEST_MAX_TOKENS,
) -> list[DigestSection]:
    """Synthesize digest sections from already-selected candidates."""

    scope = f" for category {category}" if category else ""
    user = DIGEST_USER_TEMPLATE.format(
        period=period.label,
        scope=scope,
        candidates=candidate_text or "(no candidate material)",
    )
    data = client.complete_json(
        operation="digest",
        system=DIGEST_SYSTEM_PROMPT,
        user=user,
        max_tokens=max_tokens,
    )

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
