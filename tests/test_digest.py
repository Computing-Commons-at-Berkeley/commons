from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from commons.community_repo.digests import (
    list_digests,
    parse_digest_artifact,
    plan_digest_name,
    render_digest_artifact,
)
from commons.community_repo.schemas import DigestArtifact, DigestSection
from commons.digest import (
    ChannelActivity,
    DigestMessage,
    DigestPeriod,
    build_candidate_text,
    generate_digest,
)
from commons.discord.digest import DigestRequest, DigestService
from commons.errors import DigestError
from fakes import FakeLLMClient, FakeRepo

DIGEST_PAYLOAD = {
    "sections": [
        {"heading": "Notable Discussions", "body": "- batching and tail latency"},
        {"heading": "Open Questions", "body": "- which scheduler config is safe?"},
    ]
}


def make_activity() -> list[ChannelActivity]:
    return [
        ChannelActivity(
            channel="infra",
            messages=[
                DigestMessage(
                    channel="infra",
                    author="alice",
                    content="tail latency",
                    created_at="2026-01-01T00:00+00:00",
                    jump_url="https://discord.test/1",
                ),
                DigestMessage(channel="infra", author="bob", content="   ", created_at=None),
            ],
        )
    ]


def test_period_from_label() -> None:
    now = datetime(2026, 1, 8, tzinfo=UTC)
    period = DigestPeriod.from_label("7d", now=now)
    assert period.label == "7d"
    assert period.end == now
    assert period.start == now - timedelta(days=7)
    assert DigestPeriod.from_label("1d", now=now).start == now - timedelta(days=1)


def test_period_rejects_unknown_label() -> None:
    with pytest.raises(DigestError):
        DigestPeriod.from_label("2w")


def test_build_candidate_text_skips_empty_and_truncates() -> None:
    text = build_candidate_text(make_activity())
    assert "## #infra" in text
    assert "alice" in text
    assert "bob" not in text

    truncated = build_candidate_text(make_activity(), max_chars=10)
    assert truncated.endswith("[candidates truncated]")


def test_generate_digest_parses_sections() -> None:
    client = FakeLLMClient(DIGEST_PAYLOAD)
    period = DigestPeriod.from_label("7d", now=datetime(2026, 1, 8, tzinfo=UTC))
    sections = generate_digest(client, period=period, candidate_text="alice: hi")
    assert [section.heading for section in sections] == ["Notable Discussions", "Open Questions"]
    assert client.operations == ["digest"]


def test_generate_digest_requires_sections() -> None:
    client = FakeLLMClient({"sections": []})
    with pytest.raises(DigestError):
        generate_digest(client, period=DigestPeriod.from_label("7d"), candidate_text="x")


def test_digest_render_parse_round_trip() -> None:
    artifact = DigestArtifact(
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 8, tzinfo=UTC),
        generated_at=datetime(2026, 1, 8, 12, tzinfo=UTC),
        sections=[DigestSection(heading="ML Research", body="- paper")],
    )
    parsed = parse_digest_artifact(render_digest_artifact(artifact))
    assert parsed.period_start == artifact.period_start
    assert [section.heading for section in parsed.sections] == ["ML Research"]
    assert parsed.sections[0].body == "- paper"


def test_plan_digest_name() -> None:
    start = datetime(2026, 9, 20, tzinfo=UTC)
    assert plan_digest_name(start, "7d") == "2026-09-20-7d"
    assert plan_digest_name(start, "7d", category="infra") == "2026-09-20-7d-infra"


def test_digest_service_generates_and_writes(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = DigestService(repo, FakeLLMClient(DIGEST_PAYLOAD))

    outcome = service.generate(
        DigestRequest(period="7d", activity=make_activity(), requested_by="alice")
    )

    assert outcome.section_headings == ["Notable Discussions", "Open Questions"]
    assert outcome.relative_path.startswith("data/digests/")
    assert outcome.relative_path.endswith("-7d.md")
    parsed = parse_digest_artifact((repo.path / outcome.relative_path).read_text(encoding="utf-8"))
    assert parsed.sections[0].heading == "Notable Discussions"
    assert repo.commits[-1].startswith("digest: add ")
    assert len(list_digests(repo.path / "data")) == 1


def test_digest_service_rejects_empty_activity(tmp_path: Path) -> None:
    service = DigestService(FakeRepo(tmp_path / "community"), FakeLLMClient(DIGEST_PAYLOAD))
    with pytest.raises(DigestError):
        service.generate(DigestRequest(period="1d", activity=[], requested_by="alice"))
