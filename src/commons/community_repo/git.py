"""Safe writes to the private community repository.

Every durable write follows the sequence mandated by plan section 16:

    acquire lock -> git pull --rebase -> write -> git add -> commit -> push -> release lock

If push fails we raise GitPushError. The local commit is kept, and the caller
must not report success. Automation failure degrades convenience; it never
disables the community.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from commons.errors import GitError, GitPushError
from commons.logging import get_logger

log = get_logger(__name__)

DEFAULT_BOT_NAME = "Technical Commons Bot"
DEFAULT_BOT_EMAIL = "technical-commons-bot@users.noreply.github.com"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class GitWriteResult:
    relative_path: str
    committed: bool
    pushed: bool
    commit_sha: str | None
    detail: str = ""


class CommunityRepo:
    """A local checkout of the private community repository."""

    def __init__(
        self,
        path: Path,
        *,
        remote: str = "origin",
        branch: str | None = None,
        bot_name: str = DEFAULT_BOT_NAME,
        bot_email: str = DEFAULT_BOT_EMAIL,
        lock_path: Path | None = None,
        lock_timeout: float = 120.0,
    ) -> None:
        self.path = Path(path)
        self.remote = remote
        self._branch = branch
        self.bot_name = bot_name
        self.bot_email = bot_email
        self.lock_path = Path(lock_path) if lock_path is not None else None
        self.lock_timeout = lock_timeout

    # --- basics ---------------------------------------------------------
    def _git(self, *args: str, check: bool = False) -> CommandResult:
        command = ["git", "-C", str(self.path), *args]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        result = CommandResult(
            returncode=process.returncode,
            stdout=(process.stdout or "").strip(),
            stderr=(process.stderr or "").strip(),
        )
        if check and not result.ok:
            raise GitError(
                f"git {' '.join(args)} failed ({result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        return result

    def is_repo(self) -> bool:
        if not (self.path / ".git").exists():
            return False
        return self._git("rev-parse", "--git-dir").ok

    def current_branch(self) -> str:
        if self._branch:
            return self._branch
        return self._git("rev-parse", "--abbrev-ref", "HEAD", check=True).stdout

    def head_sha(self) -> str | None:
        result = self._git("rev-parse", "HEAD")
        return result.stdout if result.ok else None

    def staged_paths(self) -> list[str]:
        return [
            line
            for line in self._git("diff", "--cached", "--name-only").stdout.splitlines()
            if line
        ]

    # --- lock -----------------------------------------------------------
    @contextmanager
    def lock(self, timeout: float | None = None) -> Iterator[None]:
        """Serialize durable writes across processes on this host."""

        if self.lock_path is None:
            yield
            return

        deadline = time.monotonic() + (self.lock_timeout if timeout is None else timeout)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle: int | None = None
        while handle is None:
            try:
                handle = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._lock_is_stale():
                    log.warning("removing stale community repo lock at %s", self.lock_path)
                    try:
                        os.unlink(self.lock_path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise GitError(
                        f"could not acquire community repo lock at {self.lock_path}"
                    ) from None
                time.sleep(0.1)
        try:
            os.write(handle, f"{os.getpid()}\n".encode())
            yield
        finally:
            if handle is not None:
                os.close(handle)
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass

    def _lock_is_stale(self) -> bool:
        assert self.lock_path is not None
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except OSError:
            return False
        return age > self.lock_timeout

    # --- write path -----------------------------------------------------
    def pull_rebase(self) -> CommandResult:
        branch = self.current_branch()
        result = self._git("pull", "--rebase", self.remote, branch)
        if not result.ok:
            # Never leave a half-finished rebase behind.
            self._git("rebase", "--abort")
        return result

    def add(self, relative_path: str) -> None:
        self._git("add", "--", relative_path, check=True)

    def commit(self, message: str) -> str:
        self._git(
            "-c",
            f"user.name={self.bot_name}",
            "-c",
            f"user.email={self.bot_email}",
            "commit",
            "-m",
            message,
            check=True,
        )
        sha = self._git("rev-parse", "HEAD", check=True).stdout
        return sha

    def push(self) -> CommandResult:
        return self._git("push", self.remote, self.current_branch())

    def write_artifact(
        self,
        relative_path: str,
        content: str,
        *,
        commit_message: str,
    ) -> GitWriteResult:
        """Write one artifact and persist it, or fail loudly."""

        if not self.is_repo():
            raise GitError(f"{self.path} is not a git repository")

        with self.lock():
            pull = self.pull_rebase()
            if not pull.ok:
                log.warning(
                    "git pull --rebase did not succeed; continuing with local state: %s",
                    pull.stderr or pull.stdout,
                )

            target = self.path / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            # Force LF so artifacts are byte-stable across platforms (see D006).
            target.write_text(content, encoding="utf-8", newline="\n")
            self.add(relative_path)

            if not self.staged_paths():
                return GitWriteResult(
                    relative_path=relative_path,
                    committed=False,
                    pushed=False,
                    commit_sha=None,
                    detail="no changes to commit",
                )

            sha = self.commit(commit_message)
            push = self.push()
            if not push.ok:
                raise GitPushError(
                    f"committed {sha} but failed to push to "
                    f"{self.remote}/{self.current_branch()}: {push.stderr or push.stdout}"
                )
            return GitWriteResult(
                relative_path=relative_path,
                committed=True,
                pushed=True,
                commit_sha=sha,
            )
