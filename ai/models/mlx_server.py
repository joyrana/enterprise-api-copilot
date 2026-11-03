"""mlx-lm server provider (``ModelProvider``) over plain httpx — the default local LLM.

Talks to ``mlx_lm.server`` (Apple Silicon), which serves the OpenAI-compatible
``POST {base_url}/v1/chat/completions``. Start it with, for example::

    mlx_lm.server --model mlx-community/Qwen3-4B-Instruct-2507-4bit --port 8000

(``--port`` is required: the server's own default, 8080, is the platform API's port.)
The server loads whatever model a request names, so ``COPILOT_LLM_MODEL`` must match
the ``--model`` it was started with, or it downloads and loads a second model.

When the request carries a JSON schema the schema is stated in the system prompt and
also sent as ``response_format`` (mlx-lm 0.29 ignores it; ``generate_structured``
validates the reply either way). The default model is the non-thinking Instruct-2507
variant; for hybrid Qwen3 checkpoints start the server with
``--chat-template-args '{"enable_thinking":false}'``. Any ``<think>`` block is stripped.
Untrusted context is wrapped and sent as user content, never merged into the system
prompt.
"""

from __future__ import annotations

import json
import re
import time

import httpx

from ai.models.base import ModelRequest, ModelResponse, ModelUnavailableError, ModelUsage

DEFAULT_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)


class MLXServerProvider:
    name = "mlx"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 120.0,
        thinking: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._thinking = thinking
        self._transport = transport

    async def generate(self, request: ModelRequest) -> ModelResponse:
        system = request.system
        if request.json_schema is not None:
            system += (
                "\n\nReply with a single JSON object and nothing else (no prose, no code "
                "fences) that conforms to this JSON Schema:\n"
                + json.dumps(request.json_schema, separators=(",", ":"))
            )
        user = request.user
        if request.untrusted_context:
            user = (
                f"<untrusted_context>\n{request.untrusted_context}\n</untrusted_context>\n\n{user}"
            )
        body: dict[str, object] = {
            "model": self.model,
            "stream": False,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "chat_template_kwargs": {"enable_thinking": self._thinking},
        }
        if request.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.task, "schema": request.json_schema},
            }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(f"{self._base}/v1/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(
                f"mlx-lm server at {self._base} is unreachable ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            raise ModelUnavailableError(
                f"mlx-lm server returned HTTP {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        choices = data.get("choices") or [{}]
        text = str((choices[0].get("message") or {}).get("content") or "")
        raw_usage = data.get("usage") or {}
        usage = ModelUsage(
            input_tokens=int(raw_usage.get("prompt_tokens", 0)),
            output_tokens=int(raw_usage.get("completion_tokens", 0)),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return ModelResponse(
            text=_THINK.sub("", text).strip(),
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage=usage,
        )
