from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from commons.community_repo.artifacts import parse_knowledge_artifact
from commons.community_repo.git import CommunityRepo, GitWriteResult
from commons.community_repo.schemas import DiscordSource
from commons.discord.archive import ArchiveRequest, ArchiveService, TranscriptMessage
from commons.errors import ArchiveError, GitPushError
from fakes import FakeLLMClient


def make_request() -> ArchiveRequest:
    return ArchiveRequest(
        source=DiscordSource(
            guild_id=1,
            discord_channel_id=2,
            discord_channel_name="infra",
            discord_message_id=3,
            discord_thread_id=4,
            discord_message_url="https://discord.com/channels/1/2/3",
            discord_author="alice",
        ),
        messages=[
            TranscriptMessage(
                author="alice",
                content="The scheduler batching policy may raise tail latency.",
                created_at="2026-01-01T00:00+00:00",
            ),
            TranscriptMessage(author="bob", content="Let us measure it.", created_at=None),
        ],
        requested_by="alice",
        title_hint="batching",
        channel_name="infra",
    )


class FakeRepo:
    """A CommunityRepo stand-in that writes files without touching Git."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.commits: list[str] = []

    def write_artifact(
        self, relative_path: str, content: str, *, commit_message: str
    ) -> GitWriteResult:
        target = self.path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.commits.append(commit_message)
        return GitWriteResult(
            relative_path=relative_path, committed=True, pushed=True, commit_sha="deadbeef"
        )


def test_archive_writes_artifact_end_to_end_without_git(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "community")
    service = ArchiveService(repo, FakeLLMClient())

    outcome = service.archive(make_request())

    assert outcome.created is True
    artifact_path = repo.path / outcome.relative_path
    parsed = parse_knowledge_artifact(artifact_path.read_text(encoding="utf-8"))
    assert parsed.title == "SGLang scheduling notes"
    assert parsed.source.discord_thread_id == 4
    assert parsed.source.discord_message_url == "https://discord.com/channels/1/2/3"
    assert repo.commits == ["archive: add note on SGLang scheduling notes"]

    second = service.archive(make_request())
    assert second.created is False
    assert second.relative_path == outcome.relative_path


def test_archive_creates_provenance_preserving_artifact(
    repo_with_remote, tmp_path: Path, local_push_supported: bool
) -> None:
    if not local_push_supported:
        pytest.skip("local git push is unavailable in this sandbox; covered in CI")

    repo = CommunityRepo(repo_with_remote.path, lock_path=tmp_path / "lock")
    service = ArchiveService(repo, FakeLLMClient())
    outcome = service.archive(make_request())

    assert outcome.created is True
    assert outcome.commit_sha
    log = subprocess.run(
        ["git", "-C", str(repo_with_remote.remote), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "archive: add note on SGLang scheduling notes" in log.stdout


def test_archive_is_idempotent_for_the_same_source(
    repo_with_remote, tmp_path: Path, local_push_supported: bool
) -> None:
    if not local_push_supported:
        pytest.skip("local git push is unavailable in this sandbox; covered in CI")

    repo = CommunityRepo(repo_with_remote.path, lock_path=tmp_path / "lock")
    llm = FakeLLMClient()
    service = ArchiveService(repo, llm)

    first = service.archive(make_request())
    second = service.archive(make_request())

    assert first.created is True
    assert second.created is False
    assert second.relative_path == first.relative_path
    assert len(llm.operations) == 1


def test_archive_reports_push_failure(repo_without_remote, tmp_path: Path) -> None:
    repo = CommunityRepo(repo_without_remote.path, lock_path=tmp_path / "lock")
    service = ArchiveService(repo, FakeLLMClient())
    with pytest.raises(GitPushError):
        service.archive(make_request())


def test_archive_rejects_empty_transcript(repo_with_remote, tmp_path: Path) -> None:
    repo = CommunityRepo(repo_with_remote.path, lock_path=tmp_path / "lock")
    service = ArchiveService(repo, FakeLLMClient())
    request = ArchiveRequest(
        source=DiscordSource(discord_message_id=99),
        messages=[TranscriptMessage(author="alice", content="   ")],
        requested_by="alice",
    )
    with pytest.raises(ArchiveError):
        service.archive(request)


def test_render_transcript_truncates() -> None:
    from commons.discord.archive import render_transcript

    messages = [TranscriptMessage(author="a", content="x" * 200)]
    text = render_transcript(messages, max_chars=50)
    assert text.endswith("[transcript truncated]")


def test_archive_end_to_end_commits_locally_without_push(
    repo_without_remote, tmp_path: Path
) -> None:
    """Full path against real Git: Discord payload -> artifact -> local commit.

    The push is unavailable in this sandbox, so we assert on the locally
    committed artifact and on idempotency; CI covers the push itself.
    """

    repo = CommunityRepo(repo_without_remote.path, lock_path=tmp_path / "lock")
    service = ArchiveService(repo, FakeLLMClient())

    with pytest.raises(GitPushError):
        service.archive(make_request())

    artifacts = list((repo_without_remote.path / "data" / "knowledge").glob("*.md"))
    assert len(artifacts) == 1

    parsed = parse_knowledge_artifact(artifacts[0].read_text(encoding="utf-8"))
    assert parsed.title == "SGLang scheduling notes"
    assert parsed.source.discord_message_id == 3
    assert parsed.source.discord_thread_id == 4

    log = subprocess.run(
        ["git", "-C", str(repo_without_remote.path), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "archive: add note on SGLang scheduling notes" in log.stdout

    second = service.archive(make_request())
    assert second.created is False
