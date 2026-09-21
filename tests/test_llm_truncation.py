"""Regression tests for truncated LLM output and runaway retries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from commons.digest import DIGEST_MAX_TOKENS, DigestPeriod, generate_digest
from commons.errors import LLMError
from commons.llm import LLMClient
from commons.scheduler import MAX_PROMPT_RETRIES, Scheduler


def make_client(payload: dict, captured: dict | None = None) -> LLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.update(json.loads(request.content))
        return httpx.Response(200, json=payload)

    return LLMClient(
        api_key="k",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(handler),
    )


def test_truncated_output_raises_a_clear_error() -> None:
    client = make_client(
        {
            "choices": [
                {
                    "message": {"content": '{"sections": [{"heading": "ML'},
                    "finish_reason": "length",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1200},
        }
    )
    with pytest.raises(LLMError) as excinfo:
        client.complete(operation="digest", system="s", user="u")
    assert "truncated" in str(excinfo.value)


def test_digest_gets_a_budget_larger_than_the_archive_default() -> None:
    captured: dict = {}
    payload = {
        "choices": [
            {
                "message": {"content": json.dumps({"sections": [{"heading": "H", "body": "b"}]})},
                "finish_reason": "stop",
            }
        ]
    }
    client = make_client(payload, captured)
    sections = generate_digest(
        client, period=DigestPeriod.from_label("7d"), candidate_text="candidates"
    )

    assert [section.heading for section in sections] == ["H"]
    assert captured["max_tokens"] == DIGEST_MAX_TOKENS
    assert DIGEST_MAX_TOKENS > 1200


def test_repeated_failures_back_off_to_the_full_interval() -> None:
    def boom() -> None:
        raise RuntimeError("deterministic failure")

    scheduler = Scheduler()
    job = scheduler.add("flaky", timedelta(days=7), boom, retry_interval=timedelta(minutes=5))
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    current = moment
    for _ in range(MAX_PROMPT_RETRIES):
        scheduler.run_pending(now=current)
        current += timedelta(minutes=5)

    assert job.failures == MAX_PROMPT_RETRIES
    assert job.next_due is not None
    assert job.next_due - moment >= timedelta(days=7)
