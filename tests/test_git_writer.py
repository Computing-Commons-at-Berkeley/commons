from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from commons.community_repo.git import CommandResult, CommunityRepo
from commons.errors import GitError, GitPushError


def _repo(fixture, tmp_path: Path) -> CommunityRepo:
    return CommunityRepo(fixture.path, lock_path=tmp_path / "lock")


def test_write_artifact_commits_and_pushes(
    repo_with_remote, tmp_path: Path, local_push_supported: bool
) -> None:
    if not local_push_supported:
        pytest.skip("local git push is unavailable in this sandbox; covered in CI")

    repo = _repo(repo_with_remote, tmp_path)
    result = repo.write_artifact("data/knowledge/a.md", "hello\n", commit_message="archive: add a")

    assert result.committed is True
    assert result.pushed is True
    assert result.commit_sha
    assert (repo_with_remote.path / "data" / "knowledge" / "a.md").read_text(
        encoding="utf-8"
    ) == "hello\n"

    log = subprocess.run(
        ["git", "-C", str(repo_with_remote.remote), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "archive: add a" in log.stdout


def test_write_artifact_is_idempotent_for_identical_content(
    repo_with_remote, tmp_path: Path, local_push_supported: bool
) -> None:
    repo = _repo(repo_with_remote, tmp_path)
    if local_push_supported:
        assert repo.write_artifact(
            "data/knowledge/a.md", "hello\n", commit_message="archive: add a"
        ).committed
    else:
        with pytest.raises(GitPushError):
            repo.write_artifact("data/knowledge/a.md", "hello\n", commit_message="archive: add a")

    second = repo.write_artifact("data/knowledge/a.md", "hello\n", commit_message="archive: add a")
    assert second.committed is False
    assert second.pushed is False


def test_write_artifact_never_fakes_success_on_push_failure(
    repo_without_remote, tmp_path: Path
) -> None:
    repo = _repo(repo_without_remote, tmp_path)
    with pytest.raises(GitPushError) as excinfo:
        repo.write_artifact("data/knowledge/a.md", "hello\n", commit_message="archive: add a")

    assert "failed to push" in str(excinfo.value)
    assert (repo_without_remote.path / "data" / "knowledge" / "a.md").exists()
    log = subprocess.run(
        ["git", "-C", str(repo_without_remote.path), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "archive: add a" in log.stdout


def test_write_artifact_success_flow_with_fake_runner(tmp_path: Path) -> None:
    """Deterministic coverage of the success path, independent of the sandbox."""

    class RecordingRepo(CommunityRepo):
        def __init__(self, path: Path, **kwargs) -> None:
            super().__init__(path, **kwargs)
            self.commands: list[tuple[str, ...]] = []

        def is_repo(self) -> bool:
            return True

        def _git(self, *args: str, check: bool = False) -> CommandResult:
            self.commands.append(args)
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return CommandResult(0, "main", "")
            if args[:2] == ("rev-parse", "HEAD"):
                return CommandResult(0, "abc123", "")
            if args and args[0] == "diff":
                return CommandResult(0, "data/knowledge/a.md", "")
            return CommandResult(0, "", "")

    repo = RecordingRepo(tmp_path / "community", lock_path=None)
    result = repo.write_artifact("data/knowledge/a.md", "x\n", commit_message="archive: add a")

    assert result.committed is True
    assert result.pushed is True
    assert result.commit_sha == "abc123"
    assert any(command and command[0] == "push" for command in repo.commands)


def test_lock_prevents_concurrent_writes(repo_with_remote, tmp_path: Path) -> None:
    repo = _repo(repo_with_remote, tmp_path)
    with repo.lock():
        with pytest.raises(GitError):
            with repo.lock(timeout=0.0):
                pass


def test_non_repo_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "not-a-repo"
    path.mkdir()
    repo = CommunityRepo(path, lock_path=tmp_path / "lock")
    with pytest.raises(GitError):
        repo.write_artifact("data/knowledge/a.md", "x", commit_message="archive: add a")


def test_pull_rebase_aborts_a_failed_rebase(tmp_path: Path) -> None:
    class PullFailRepo(CommunityRepo):
        def __init__(self, path: Path, **kwargs) -> None:
            super().__init__(path, **kwargs)
            self.commands: list[tuple[str, ...]] = []

        def _git(self, *args: str, check: bool = False) -> CommandResult:
            self.commands.append(args)
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return CommandResult(0, "main", "")
            if args and args[0] == "pull":
                return CommandResult(1, "", "conflict")
            return CommandResult(0, "", "")

    repo = PullFailRepo(tmp_path / "community", lock_path=None)
    result = repo.pull_rebase()

    assert result.ok is False
    assert ("rebase", "--abort") in repo.commands
