"""Safe writes to the private community repository.

Every durable write follows the sequence mandated by plan section 16:

    acquire lock -> git pull --rebase -> write -> git add -> commit -> push -> release lock

Correctness rules from the 2026-09-19 review:

- the artifact path is chosen inside the lock, after synchronizing, so two
  concurrent requests cannot reserve the same filename (R02);
- an unexpected dirty index stops the write, and only our own artifact is ever
  committed (R03);
- a failed push is never reported as success, and a retry keeps the pending
  state visible until an explicit recovery (R04);
- the lock always honors its deadline and Git subprocesses are bounded (R09).
"""

from __future__ import annotations

import errno
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from commons.errors import GitError, GitPushError
from commons.logging import get_logger

log = get_logger(__name__)

DEFAULT_BOT_NAME = "Technical Commons Bot"
DEFAULT_BOT_EMAIL = "technical-commons-bot@users.noreply.github.com"
DEFAULT_GIT_TIMEOUT = 120.0
PUSHED_REF = "refs/tc/last-pushed"


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


@dataclass(frozen=True)
class ArtifactPlan:
    """What a workflow wants to write, decided inside the repository lock."""

    relative_path: str
    content: str | None = None  # None means the artifact already exists
    detail: str = ""


@dataclass(frozen=True)
class LockedWriteResult:
    plan: ArtifactPlan | None
    git: GitWriteResult


def _file_lock(handle: int, *, unlock: bool = False) -> None:
    """OS-owned locks survive slow work and are released on process exit."""
    if os.name == "nt":
        import msvcrt

        os.lseek(handle, 0, os.SEEK_SET)
        msvcrt.locking(handle, msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


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
        git_timeout: float = DEFAULT_GIT_TIMEOUT,
    ) -> None:
        self.path = Path(path)
        self.remote = remote
        self._branch = branch
        self.bot_name = bot_name
        self.bot_email = bot_email
        self.lock_path = Path(lock_path) if lock_path is not None else None
        self.lock_timeout = lock_timeout
        self.git_timeout = git_timeout

    # --- basics ---------------------------------------------------------
    def _git(self, *args: str, check: bool = False) -> CommandResult:
        command = ["git", "-C", str(self.path), *args]
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=self.git_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {self.git_timeout:.0f}s") from exc
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

    def remote_configured(self) -> bool:
        return bool(self._git("remote").stdout.strip())

    def has_remote_tracking(self) -> bool:
        ref = f"{self.remote}/{self.current_branch()}"
        return self._git("rev-parse", "--verify", ref).ok

    def has_unpushed_commits(self) -> bool:
        """True when local commits are not known to be on the remote (R04)."""

        head = self.head_sha()
        if head is None:
            return False

        if not self.remote_configured():
            return True

        ref = self._git("rev-parse", "--verify", f"{self.remote}/{self.current_branch()}")
        if not ref.ok:
            return True
        # The custom marker may predate a maintainer's push or our own pull.
        # Only the synchronized remote's graph establishes remote persistence.
        result = self._git("merge-base", "--is-ancestor", head, ref.stdout)
        if result.returncode not in (0, 1):
            raise GitError(f"could not compare local and remote commits: {result.stderr}")
        return result.returncode == 1

    def has_pending_unpushed(self) -> bool:
        """A divergence from an established remote branch that needs recovery."""

        return (
            self.remote_configured() and self.has_remote_tracking() and self.has_unpushed_commits()
        )

    def _mark_pushed(self) -> None:
        head = self.head_sha()
        if head is not None:
            self._git("update-ref", PUSHED_REF, head)

    def ensure_clean_index(self) -> None:
        staged = self.staged_paths()
        if staged:
            raise GitError(
                "refusing to write: the community checkout already has staged "
                f"changes ({', '.join(staged)}); commit or unstage them first"
            )

    # --- lock -----------------------------------------------------------
    @contextmanager
    def lock(self, timeout: float | None = None) -> Iterator[None]:
        """Serialize durable writes across processes on this host."""

        if self.lock_path is None:
            yield
            return

        deadline = time.monotonic() + (self.lock_timeout if timeout is None else timeout)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the file: unlinking it can create two independently locked inodes.
        handle = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            while not acquired:
                try:
                    _file_lock(handle)
                    acquired = True
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise GitError(f"cannot lock {self.lock_path}: {exc}") from exc
                    if time.monotonic() >= deadline:
                        raise GitError(
                            f"could not acquire community repo lock at {self.lock_path}"
                        ) from exc
                    time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            yield
        finally:
            try:
                if acquired:
                    _file_lock(handle, unlock=True)
            finally:
                os.close(handle)

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
        return self._git("rev-parse", "HEAD", check=True).stdout

    def push(self) -> CommandResult:
        return self._git("push", self.remote, self.current_branch())

    def _settle_pending(self, relative_path: str, detail: str = "") -> GitWriteResult:
        if not self.has_unpushed_commits():
            return GitWriteResult(
                relative_path=relative_path,
                committed=False,
                pushed=False,
                commit_sha=None,
                detail=detail or "no changes to commit",
            )
        raise GitPushError(
            f"{relative_path} has pending local commits; push them explicitly "
            "and retry after verifying the remote"
        )

    def write_artifact_locked(
        self,
        *,
        commit_message: str,
        prepare: Callable[[Path], ArtifactPlan | None],
    ) -> LockedWriteResult:
        """Synchronize, then let prepare choose the path and content inside the lock."""

        if not self.is_repo():
            raise GitError(f"{self.path} is not a git repository")

        with self.lock():
            self.ensure_clean_index()

            pull = self.pull_rebase()
            if not pull.ok:
                if self.has_remote_tracking():
                    raise GitError(
                        "could not synchronize with the remote before writing: "
                        f"{pull.stderr or pull.stdout}"
                    )
                log.info("no remote tracking branch yet; treating this as initial setup")

            if self.has_pending_unpushed():
                raise GitPushError(
                    "the community checkout has unpushed commits; push or reset them "
                    "explicitly before creating new artifacts"
                )

            plan = prepare(self.path)
            if plan is None:
                return LockedWriteResult(
                    plan=None,
                    git=GitWriteResult("", committed=False, pushed=False, commit_sha=None),
                )
            if plan.content is None:
                return LockedWriteResult(plan=plan, git=self._settle_pending(plan.relative_path))

            target = self.path / plan.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            # Force LF so artifacts are byte-stable across platforms (see D006).
            target.write_text(plan.content, encoding="utf-8", newline="\n")
            self.add(plan.relative_path)

            staged = self.staged_paths()
            if not staged:
                return LockedWriteResult(
                    plan=plan,
                    git=self._settle_pending(plan.relative_path, "no changes to commit"),
                )
            if staged != [plan.relative_path]:
                raise GitError(
                    f"refusing to commit unexpected staged paths {staged}; "
                    f"expected only {plan.relative_path}"
                )

            sha = self.commit(commit_message)
            push = self.push()
            if not push.ok:
                raise GitPushError(
                    f"committed {sha} but failed to push to "
                    f"{self.remote}/{self.current_branch()}: {push.stderr or push.stdout}"
                )
            self._mark_pushed()
            return LockedWriteResult(
                plan=plan,
                git=GitWriteResult(
                    relative_path=plan.relative_path,
                    committed=True,
                    pushed=True,
                    commit_sha=sha,
                ),
            )

    def write_artifact(
        self,
        relative_path: str,
        content: str,
        *,
        commit_message: str,
    ) -> GitWriteResult:
        """Write one artifact at a pre-chosen path (used by deterministic paths)."""

        def prepare(_root: Path) -> ArtifactPlan:
            return ArtifactPlan(relative_path=relative_path, content=content)

        return self.write_artifact_locked(commit_message=commit_message, prepare=prepare).git
