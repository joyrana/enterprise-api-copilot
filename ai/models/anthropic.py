"""Opt-in Anthropic Messages API provider (``ModelProvider``) over plain httpx.

Used only when explicitly configured (``COPILOT_JUDGE_PROVIDER=anthropic`` plus
``ANTHROPIC_API_KEY``); default CI never calls it (ADR-0008). The request follows the
Messages API: ``POST {base_url}/v1/messages`` with ``x-api-key`` and ``anthropic-version``.
Trusted instructions go in ``system``; untrusted context is wrapped and sent as user
content, never merged into the system prompt. The API key is never logged.

Not exercised against the live API in the session that wrote it (no key available).
"""

from __future__ import annotations

import os
import time

import httpx

from ai.models.base import ModelRequest, ModelResponse, ModelUsage, PriceTable

API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = "https://api.anthropic.com",
        prices: PriceTable | None = None,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for the anthropic provider")
        self._key = api_key
        self.model = model
        self._base = base_url.rstrip("/")
        self._prices = prices or PriceTable()
        self._timeout = timeout_s
        self._transport = transport

    @classmethod
    def from_env(cls) -> AnthropicProvider:
        return cls(
            os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("COPILOT_JUDGE_MODEL", DEFAULT_MODEL),
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        user = request.user
        if request.untrusted_context:
            user = (
                f"<untrusted_context>\n{request.untrusted_context}\n</untrusted_context>\n\n{user}"
            )
        body = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": user}],
        }
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                f"{self._base}/v1/messages",
                json=body,
                headers={
                    "x-api-key": self._key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
            )
        if response.status_code != 200:
            raise RuntimeError(f"anthropic API returned HTTP {response.status_code}")
        data = response.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        raw_usage = data.get("usage", {})
        usage = ModelUsage(
            input_tokens=int(raw_usage.get("input_tokens", 0)),
            output_tokens=int(raw_usage.get("output_tokens", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        usage.estimated_cost_usd = self._prices.cost(self.model, usage)
        return ModelResponse(
            text=text, model=str(data.get("model", self.model)), provider=self.name, usage=usage
        )
