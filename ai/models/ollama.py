"""Ollama chat provider (``ModelProvider``) over plain httpx — the default local LLM.

``POST {base_url}/api/chat`` with ``stream: false``. When the request carries a JSON
schema it is passed as ``format`` so the server constrains decoding to that schema
(structured outputs); ``generate_structured`` still validates the result. Thinking is
off by default: the agent asks for short structured decisions, where hidden reasoning
mostly adds latency. Untrusted context is wrapped and sent as user content, never merged
into the system prompt.

Defaults target ``qwen3.5:9b`` on ``http://127.0.0.1:11434`` (see ``.env.example``).
"""

from __future__ import annotations

import time

import httpx

from ai.models.base import ModelRequest, ModelResponse, ModelUnavailableError, ModelUsage

DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 120.0,
        num_ctx: int = 16384,
        think: bool = False,
        keep_alive: str = "30m",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._num_ctx = num_ctx
        self._think = think
        self._keep_alive = keep_alive
        self._transport = transport

    async def generate(self, request: ModelRequest) -> ModelResponse:
        user = request.user
        if request.untrusted_context:
            user = (
                f"<untrusted_context>\n{request.untrusted_context}\n</untrusted_context>\n\n{user}"
            )
        body: dict[str, object] = {
            "model": self.model,
            "stream": False,
            "think": self._think,
            "keep_alive": self._keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
                "num_ctx": self._num_ctx,
            },
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": user},
            ],
        }
        if request.json_schema is not None:
            body["format"] = request.json_schema
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(f"{self._base}/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(
                f"ollama at {self._base} is unreachable ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            raise ModelUnavailableError(
                f"ollama returned HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        usage = ModelUsage(
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return ModelResponse(
            text=str((data.get("message") or {}).get("content", "")),
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage=usage,
        )
