from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from commons.errors import LLMError
from commons.llm import LLMClient, UsageLog, estimate_cost, summarize_archive


def make_client(handler, tmp_path: Path) -> LLMClient:
    return LLMClient(
        api_key="test-key",
        model="gpt-4o-mini",
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(handler),
        usage_log=UsageLog(tmp_path / "usage.jsonl"),
    )


def _response(
    content: str, prompt_tokens: int = 100, completion_tokens: int = 50
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def test_summarize_archive_parses_json_and_records_usage(tmp_path: Path) -> None:
    payload = {
        "title": "Scheduling",
        "summary": "Batching policy can raise tail latency.",
        "key_points": ["batching"],
        "open_questions": [],
        "tags": ["Infra"],
        "references": ["https://example.test/x"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(json.dumps(payload))

    client = make_client(handler, tmp_path)
    draft = summarize_archive(
        client, requested_by="alice", channel="infra", title_hint="batching", transcript="alice: hi"
    )

    assert draft.title == "Scheduling"
    assert draft.tags == ["infra"]
    assert client.usage_log is not None
    assert client.usage_log.monthly_spend_usd() > 0


def test_code_fences_are_stripped(tmp_path: Path) -> None:
    fenced = '\u0060\u0060\u0060json\n{"title": "T", "summary": "S"}\n\u0060\u0060\u0060'

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(fenced)

    client = make_client(handler, tmp_path)
    data = client.complete_json(operation="x", system="s", user="u")
    assert data["title"] == "T"


def test_http_error_raises_llm_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = make_client(handler, tmp_path)
    with pytest.raises(LLMError):
        client.complete(operation="x", system="s", user="u")


def test_empty_summary_is_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response(json.dumps({"title": "T", "summary": ""}))

    client = make_client(handler, tmp_path)
    with pytest.raises(LLMError):
        summarize_archive(
            client, requested_by="a", channel="c", title_hint="", transcript="some text"
        )


def test_estimate_cost() -> None:
    assert estimate_cost("unknown-model", 1000, 1000) == 0.0
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_usage_log_survives_bad_lines(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    log.path.write_text("not json\n", encoding="utf-8")
    assert log.monthly_spend_usd() == 0.0
