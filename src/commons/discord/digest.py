"""The /digest workflow: Discord activity + news + projects -> durable digest.

Discord-free on purpose (same pattern as archive.py and project.py) so it can be
tested without a live Discord connection. Candidate collection happens in the
Discord layer; this service synthesizes and persists. Project records are read
from the community repository so the same code path serves /digest and the
scheduled weekly digest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from commons.community_repo.digests import (
    digest_relative_path,
    plan_digest_name,
    render_digest_artifact,
)
from commons.community_repo.git import CommunityRepo
from commons.community_repo.projects import list_projects
from commons.community_repo.schemas import DigestArtifact, DigestSection
from commons.digest import (
    ChannelActivity,
    DigestPeriod,
    NewsCandidate,
    ProjectCandidate,
    RadarCandidate,
    build_candidate_text,
    generate_digest,
)
from commons.errors import DigestError
from commons.llm import LLMClient


@dataclass(frozen=True)
class DigestRequest:
    period: str = "7d"
    activity: list[ChannelActivity] = field(default_factory=list)
    news: list[NewsCandidate] = field(default_factory=list)
    radar: list[RadarCandidate] = field(default_factory=list)
    projects: list[ProjectCandidate] | None = None
    category: str | None = None
    requested_by: str = "unknown"


@dataclass(frozen=True)
class DigestOutcome:
    period: str
    relative_path: str
    section_headings: list[str]
    commit_sha: str | None
    sections: list[DigestSection] = field(default_factory=list)
    detail: str = ""


def render_digest_text(outcome: DigestOutcome) -> str:
    """Render the synthesized digest for Discord delivery (R07)."""

    parts = [f"Digest ({outcome.period})"]
    for section in outcome.sections:
        parts.append(f"## {section.heading}")
        parts.append(section.body)
    return "\n\n".join(parts)


class DigestService:
    """Builds one durable digest from pre-collected candidates."""

    def __init__(
        self,
        repo: CommunityRepo,
        llm: LLMClient,
        *,
        max_article_chars: int = 12000,
        max_per_channel: int = 40,
        max_news: int = 40,
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.max_article_chars = max_article_chars
        self.max_per_channel = max_per_channel
        self.max_news = max_news

    @property
    def data_root(self) -> Path:
        return self.repo.path / "data"

    def current_projects(self) -> list[ProjectCandidate]:
        return [
            ProjectCandidate(
                title=project.title,
                status=project.status,
                goal=project.goal,
                current_state=project.current_state,
            )
            for project in list_projects(self.data_root)
        ]

    def generate(self, request: DigestRequest) -> DigestOutcome:
        period = DigestPeriod.from_label(request.period)
        projects = request.projects if request.projects is not None else self.current_projects()
        candidate_text = build_candidate_text(
            request.activity,
            news=request.news,
            projects=projects,
            radar=request.radar,
            max_chars=self.max_article_chars,
            max_per_channel=self.max_per_channel,
            max_news=self.max_news,
        )
        if not candidate_text.strip():
            raise DigestError("no candidate material to summarize for this period")

        sections = generate_digest(
            self.llm,
            period=period,
            candidate_text=candidate_text,
            category=request.category,
        )
        artifact = DigestArtifact(
            period_start=period.start,
            period_end=period.end,
            category=request.category,
            sections=sections,
        )
        name = plan_digest_name(period.start, period.label, category=request.category)
        relative_path = digest_relative_path(name)
        result = self.repo.write_artifact(
            relative_path,
            render_digest_artifact(artifact),
            commit_message=f"digest: add {name} digest",
        )
        return DigestOutcome(
            period=period.label,
            relative_path=relative_path,
            section_headings=[section.heading for section in sections],
            commit_sha=result.commit_sha,
            sections=list(sections),
            detail=result.detail,
        )
