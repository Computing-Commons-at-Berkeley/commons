from __future__ import annotations

import json

import httpx

from commons.llm import LLMClient
from commons.settings import Settings


def _handler(captured: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    return handler


def test_thinking_knob_is_forwarded() -> None:
    captured: dict[str, object] = {}
    client = LLMClient(
        api_key="k",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(_handler(captured)),
        thinking="disabled",
    )
    client.complete(operation="x", system="s", user="u")
    assert captured["thinking"] == {"type": "disabled"}


def test_thinking_is_omitted_when_unset() -> None:
    captured: dict[str, object] = {}
    client = LLMClient(
        api_key="k",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(_handler(captured)),
    )
    client.complete(operation="x", system="s", user="u")
    assert "thinking" not in captured


def test_settings_expose_thinking_toggle() -> None:
    assert Settings(_env_file=None, llm_thinking="disabled").llm_thinking == "disabled"
