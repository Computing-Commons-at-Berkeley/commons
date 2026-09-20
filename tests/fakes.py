"""Test doubles for the LLM layer."""

from __future__ import annotations

from typing import Any

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

    def complete_json(
        self, *, operation: str, system: str, user: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.operations.append(operation)
        if self.error is not None:
            raise self.error
        return dict(self.payload)
