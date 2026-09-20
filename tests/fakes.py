"""Test doubles for the LLM layer and the community repository writer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from commons.community_repo.git import ArtifactPlan, GitWriteResult, LockedWriteResult

DEFAULT_ARCHIVE_PAYLOAD: dict[str, Any] = {
    "title": "SGLang scheduling notes",
    "summary": "Members discussed batching policy and its effect on tail latency.",
    "key_points": ["Batching policy can raise tail latency"],
    "open_questions": ["Which scheduler configuration is safe?"],
    "tags": ["infra", "ml"],
    "references": ["https://example.test/issue/1"],
}


class FakeLLMClient:
    """Minimal duck-typed LLMClient for workflow tests."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = dict(payload) if payload is not None else dict(DEFAULT_ARCHIVE_PAYLOAD)
        self.error = error
        self.operations: list[str] = []
        self.user_prompts: list[str] = []

    def complete_json(
        self, *, operation: str, system: str, user: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.operations.append(operation)
        self.user_prompts.append(user)
        if self.error is not None:
            raise self.error
        return dict(self.payload)


class FakeRepo:
    """CommunityRepo stand-in that writes files without touching Git."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.commits: list[str] = []

    def write_artifact(
        self, relative_path: str, content: str, *, commit_message: str
    ) -> GitWriteResult:
        return self.write_artifact_locked(
            commit_message=commit_message,
            prepare=lambda _root: ArtifactPlan(relative_path=relative_path, content=content),
        ).git

    def write_artifact_locked(
        self,
        *,
        commit_message: str,
        prepare: Callable[[Path], ArtifactPlan | None],
    ) -> LockedWriteResult:
        plan = prepare(self.path)
        if plan is None:
            return LockedWriteResult(
                plan=None, git=GitWriteResult("", committed=False, pushed=False, commit_sha=None)
            )
        if plan.content is None:
            return LockedWriteResult(
                plan=plan,
                git=GitWriteResult(
                    plan.relative_path, committed=False, pushed=False, commit_sha=None
                ),
            )
        target = self.path / plan.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        target.write_text(plan.content, encoding="utf-8", newline="\n")
        if previous == plan.content:
            return LockedWriteResult(
                plan=plan,
                git=GitWriteResult(
                    plan.relative_path,
                    committed=False,
                    pushed=False,
                    commit_sha=None,
                    detail="no changes to commit",
                ),
            )
        self.commits.append(commit_message)
        return LockedWriteResult(
            plan=plan,
            git=GitWriteResult(
                plan.relative_path, committed=True, pushed=True, commit_sha="deadbeef"
            ),
        )
