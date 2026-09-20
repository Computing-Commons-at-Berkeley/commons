from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from commons.errors import LLMError
from commons.llm import LLMClient, LLMUsage, UsageLog, estimate_cost


def _record_usage(log: UsageLog, cost: float) -> None:
    log.record(
        LLMUsage(
            operation="test",
            model="gpt-4o-mini",
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=cost,
            created_at=datetime.now(UTC).isoformat(),
        )
    )


def test_monthly_soft_limit_warns_but_does_not_block(tmp_path: Path, caplog) -> None:
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_usage(log, 5.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = LLMClient(
        api_key="k",
        model="gpt-4o-mini",
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(handler),
        usage_log=log,
        monthly_soft_limit_usd=1.0,
    )

    with caplog.at_level("WARNING"):
        content = client.complete(operation="x", system="s", user="u")

    assert content == "ok"
    assert any("soft limit" in record.getMessage() for record in caplog.records)
    assert log.monthly_spend_usd() > 5.0


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _client(tmp_path: Path, **kwargs: object):
    log = UsageLog(tmp_path / "usage.jsonl")
    _record_usage(log, 5.0)
    return LLMClient(
        api_key="k",
        model="gpt-4o-mini",
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(_ok_handler),
        usage_log=log,
        monthly_soft_limit_usd=1.0,
        **kwargs,  # type: ignore[arg-type]
    )


def test_budget_block_refuses_further_calls(tmp_path: Path) -> None:
    client = _client(tmp_path, budget_action="block")
    with pytest.raises(LLMError):
        client.complete(operation="x", system="s", user="u")


def test_budget_warning_callback_is_invoked(tmp_path: Path) -> None:
    seen: list[str] = []
    client = _client(tmp_path, on_warning=seen.append)
    client.complete(operation="x", system="s", user="u")
    assert seen
    assert "soft limit" in seen[0]


def test_explicit_pricing_overrides_unknown_model() -> None:
    assert estimate_cost(
        "mystery",
        1_000_000,
        1_000_000,
        input_price_per_mtok=2.0,
        output_price_per_mtok=4.0,
    ) == pytest.approx(6.0)
