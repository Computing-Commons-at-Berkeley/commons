from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from commons.llm import LLMClient, LLMUsage, UsageLog


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
