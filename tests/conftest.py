"""Shared test fixtures.

Git tests run against real local repositories. The DSH sandbox blocks the POSIX
shell Git spawns for local remotes, so push-success tests are skipped when a
probe push fails; CI (GitHub Actions on Linux) exercises them for real.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

GIT_IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]


def git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@dataclass
class RepoFixture:
    path: Path
    remote: Path


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git([*GIT_IDENTITY, "init", "-b", "main"], path)
    (path / "data" / "knowledge").mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("# community\n", encoding="utf-8")
    git([*GIT_IDENTITY, "add", "-A"], path)
    git([*GIT_IDENTITY, "commit", "-m", "init"], path)


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> RepoFixture:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    path = tmp_path / "community"
    _init_repo(path)
    git(["remote", "add", "origin", str(remote)], path)
    return RepoFixture(path=path, remote=remote)


@pytest.fixture
def repo_without_remote(tmp_path: Path) -> RepoFixture:
    path = tmp_path / "community"
    _init_repo(path)
    return RepoFixture(path=path, remote=tmp_path / "missing.git")


def _probe_local_push(base: Path) -> bool:
    remote = base / "remote.git"
    work = base / "work"
    if (
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(remote)],
            capture_output=True,
            text=True,
        ).returncode
        != 0
    ):
        return False
    work.mkdir(parents=True, exist_ok=True)
    (work / "x.txt").write_text("x\n", encoding="utf-8")
    steps = [
        ["init", "-b", "main"],
        [*GIT_IDENTITY, "add", "-A"],
        [*GIT_IDENTITY, "commit", "-m", "probe"],
        ["remote", "add", "origin", str(remote)],
        [*GIT_IDENTITY, "push", "origin", "main"],
    ]
    for args in steps:
        if subprocess.run(["git", *args], cwd=work, capture_output=True, text=True).returncode != 0:
            return False
    return True


@pytest.fixture(scope="session")
def local_push_supported(tmp_path_factory: pytest.TempPathFactory) -> bool:
    """Whether this environment can push to a local bare repository."""

    return _probe_local_push(tmp_path_factory.mktemp("push-probe"))
