"""One thin LLM module.

No provider framework, no factory, no registry. If provider switching ever
becomes a real need, refactor then. Every call records token usage and an
estimated cost, and a monthly soft budget can be checked before spending.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from commons.community_repo.schemas import ArchiveDraft
from commons.errors import LLMError
from commons.logging import get_logger
from commons.prompts import ARCHIVE_SYSTEM_PROMPT, ARCHIVE_USER_TEMPLATE

log = get_logger(__name__)

# Approximate USD per 1M tokens (input, output). Unknown models estimate 0.0
# but still record tokens; cost precision is not the point, bug detection is.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


@dataclass(frozen=True)
class LLMUsage:
    operation: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_PRICES.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


class UsageLog:
    """Append-only JSONL usage log in the runtime directory.

    Runtime state is rebuildable, so this is not durable community memory. Once
    the news SQLite database exists these records can also be written there.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def record(self, usage: LLMUsage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(usage.as_dict(), ensure_ascii=False) + "\n")

    def monthly_spend_usd(self, now: datetime | None = None) -> float:
        if not self.path.exists():
            return 0.0
        moment = now or datetime.now(UTC)
        prefix = moment.strftime("%Y-%m")
        total = 0.0
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(record.get("created_at", "")).startswith(prefix):
                    total += float(record.get("estimated_cost_usd") or 0.0)
        return total


def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate[:4].lower() == "json":
            candidate = candidate[4:].strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("LLM response did not contain a JSON object") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"could not parse LLM JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("LLM JSON response must be an object")
    return parsed


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


class LLMClient:
    """A minimal OpenAI-compatible chat-completions client."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        usage_log: UsageLog | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        monthly_soft_limit_usd: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.usage_log = usage_log
        self.timeout = timeout
        self._transport = transport
        self.monthly_soft_limit_usd = monthly_soft_limit_usd

    def _check_budget(self) -> None:
        if self.usage_log is None or self.monthly_soft_limit_usd <= 0:
            return
        spent = self.usage_log.monthly_spend_usd()
        if spent >= self.monthly_soft_limit_usd:
            log.warning(
                "LLM monthly soft limit reached: spent %.4f of %.4f USD",
                spent,
                self.monthly_soft_limit_usd,
            )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(
                f"LLM request failed with status {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("LLM returned a non-JSON HTTP body") from exc
        if not isinstance(data, dict):
            raise LLMError("LLM HTTP body must be a JSON object")
        return data

    def complete(
        self,
        *,
        operation: str,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        json_mode: bool = False,
    ) -> str:
        self._check_budget()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = self._post(payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM response did not contain a message") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM returned an empty message")

        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        record = LLMUsage(
            operation=operation,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimate_cost(self.model, input_tokens, output_tokens),
            created_at=datetime.now(UTC).isoformat(),
        )
        if self.usage_log is not None:
            self.usage_log.record(record)
        log.info(
            "llm call operation=%s model=%s input_tokens=%d output_tokens=%d",
            operation,
            self.model,
            input_tokens,
            output_tokens,
        )
        return content

    def complete_json(
        self, *, operation: str, system: str, user: str, **kwargs: Any
    ) -> dict[str, Any]:
        text = self.complete(
            operation=operation, system=system, user=user, json_mode=True, **kwargs
        )
        return _extract_json(text)


def summarize_archive(
    client: LLMClient,
    *,
    requested_by: str,
    channel: str,
    title_hint: str,
    transcript: str,
) -> ArchiveDraft:
    """Turn one discussion transcript into a structured archive draft."""

    user = ARCHIVE_USER_TEMPLATE.format(
        requested_by=requested_by,
        channel=channel,
        title_hint=title_hint or "(none)",
        transcript=transcript,
    )
    data = client.complete_json(operation="archive", system=ARCHIVE_SYSTEM_PROMPT, user=user)

    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise LLMError("archive summary was empty; refusing to write an empty artifact")

    cleaned = {
        "title": str(data.get("title") or title_hint or "Untitled discussion").strip()[:120],
        "summary": summary,
        "key_points": _clean_list(data.get("key_points")),
        "open_questions": _clean_list(data.get("open_questions")),
        "tags": [tag.lower() for tag in _clean_list(data.get("tags"))][:6],
        "references": _clean_list(data.get("references")),
    }
    try:
        return ArchiveDraft.model_validate(cleaned)
    except ValidationError as exc:
        raise LLMError(f"archive summary did not match the schema: {exc}") from exc
