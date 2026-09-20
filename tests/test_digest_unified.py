from __future__ import annotations

from pathlib import Path

from commons.digest import (
    ChannelActivity,
    DigestMessage,
    DigestPeriod,
    NewsCandidate,
    ProjectCandidate,
    build_candidate_text,
    generate_digest,
)
from commons.discord.digest import DigestRequest, DigestService
from commons.discord.project import ProjectCreateRequest, ProjectService
from fakes import FakeLLMClient, FakeRepo

DIGEST_PAYLOAD = {
    "sections": [
        {"heading": "Notable Discussions", "body": "- batching"},
        {"heading": "Infrastructure", "body": "- a release"},
        {"heading": "Project Activity", "body": "- Alpha Project"},
    ]
}


def make_activity() -> list[ChannelActivity]:
    return [
        ChannelActivity(
            channel="infra",
            messages=[DigestMessage(channel="infra", author="alice", content="tail latency")],
        )
    ]


def test_build_candidate_text_includes_news_and_projects() -> None:
    text = build_candidate_text(
        make_activity(),
        news=[
            NewsCandidate(title="A paper", url="https://e.test/p", category="ml"),
            NewsCandidate(title="A release", url="https://e.test/r", category="infra"),
        ],
        projects=[ProjectCandidate(title="Alpha Project", status="active")],
    )
    assert "## #infra" in text
    assert "## News: infra" in text
    assert "## News: ml" in text
    assert "[A paper](https://e.test/p)" in text
    assert "## Projects" in text
    assert "Alpha Project (status: active)" in text


def test_generate_digest_sends_candidates_to_llm() -> None:
    client = FakeLLMClient(DIGEST_PAYLOAD)
    period = DigestPeriod.from_label("7d")
    generate_digest(client, period=period, candidate_text="## News: ml\n- [X](https://e.test)")
    assert "7d" in client.user_prompts[0]
    assert "## News: ml" in client.user_prompts[0]


def test_digest_service_includes_repo_projects(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    ProjectService(repo).create(ProjectCreateRequest(name="Alpha Project"))
    llm = FakeLLMClient(DIGEST_PAYLOAD)
    service = DigestService(repo, llm)

    outcome = service.generate(DigestRequest(period="7d", activity=make_activity()))

    assert "Alpha Project" in llm.user_prompts[0]
    assert outcome.section_headings == [
        "Notable Discussions",
        "Infrastructure",
        "Project Activity",
    ]


def test_digest_service_includes_news_candidates(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    llm = FakeLLMClient(DIGEST_PAYLOAD)
    service = DigestService(repo, llm)
    request = DigestRequest(
        period="7d",
        activity=make_activity(),
        news=[NewsCandidate(title="A paper", url="https://e.test/p", category="ml")],
    )
    service.generate(request)
    assert "[A paper](https://e.test/p)" in llm.user_prompts[0]
