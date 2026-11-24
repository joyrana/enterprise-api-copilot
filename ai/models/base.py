"""Provider-neutral model interface with structured output, usage and cost accounting.

* ``ModelProvider`` is the only thing agent code depends on; adapters implement it over
  plain httpx (``ai.models.mlx_server`` — the local default — and ``ai.models.anthropic``).
* ``generate_structured`` parses model output into a Pydantic model and raises
  ``StructuredOutputError`` instead of returning partially valid data.
* ``ScriptedModelProvider`` replays fixed responses for tests and evaluator calibration.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai.models.observe import observe_call
from skills.runtime.redaction import mask_jwts, redact_text

T = TypeVar("T", bound=BaseModel)


class ModelUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: str  # e.g. "intent", "answer", "judge"
    system: str  # trusted instructions only
    untrusted_context: str = ""  # delimited retrieved content, never merged into system
    user: str
    prompt_version: str
    max_output_tokens: int = Field(default=512, ge=1, le=8192)
    temperature: float = Field(default=0.0, ge=0, le=2)
    json_schema: dict[str, object] | None = None


class ModelResponse(BaseModel):
    text: str
    model: str
    provider: str
    usage: ModelUsage = Field(default_factory=ModelUsage)


class ModelProvider(Protocol):
    name: str
    model: str

    async def generate(self, request: ModelRequest) -> ModelResponse: ...


class StructuredOutputError(ValueError):
    pass


class ModelUnavailableError(RuntimeError):
    """The provider could not be reached or refused the request (callers fall back)."""


def sanitize_request(request: ModelRequest) -> ModelRequest:
    """Mask credentials in every text field before a request leaves the process.

    This is the single choke point for invariant 6: all agent stages call
    ``generate_structured``, which applies it to every attempt (including repair retries),
    so no call site can forget. JWTs become ``<JWT>``; other credential shapes become
    ``[REDACTED]`` (``skills.runtime.redaction``).
    """

    def clean(text: str) -> str:
        return redact_text(mask_jwts(text))

    return request.model_copy(
        update={
            "system": clean(request.system),
            "untrusted_context": clean(request.untrusted_context),
            "user": clean(request.user),
        }
    )


def _extract_json(text: str) -> str:
    """The first complete JSON object in ``text``.

    Tolerates code fences (with or without a language tag), prose before the object and
    trailing prose after it (which may itself contain braces), by decoding from each ``{``
    until one parses instead of slicing to the last ``}``.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return text[start:end]
        start = text.find("{", start + 1)
    raise StructuredOutputError("no JSON object in model output")


def inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref``s and drop ``$defs``/titles.

    Small models follow (and structured-output decoders enforce) plain nested schemas
    more reliably than reference graphs.
    """
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in {"$defs", "title"}}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)  # type: ignore[no-any-return]


async def generate_structured(
    provider: ModelProvider,
    request: ModelRequest,
    schema: type[T],
    *,
    json_schema: dict[str, Any] | None = None,
    repairs: int = 1,
) -> tuple[T, ModelResponse]:
    """``json_schema`` overrides the schema sent to the model (e.g. a narrowed enum).

    Servers without schema-constrained decoding can return malformed JSON; the request is
    repeated up to ``repairs`` times with the validation error before giving up.
    """
    sent = json_schema if json_schema is not None else inline_schema(schema.model_json_schema())
    request = request.model_copy(update={"json_schema": sent})
    attempt = request
    for remaining in range(repairs, -1, -1):
        number = repairs - remaining + 1
        sent_request = sanitize_request(attempt)
        with observe_call(request.task, request.prompt_version, number) as obs:
            try:
                response = await provider.generate(sent_request)
            except ModelUnavailableError:
                obs.finish("unavailable", provider=provider.name, model=provider.model)
                raise
            facts = {
                "provider": response.provider,
                "model": response.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "latency_ms": response.usage.latency_ms or None,
                "request_text": sent_request.system
                + "\n"
                + sent_request.untrusted_context
                + "\n"
                + sent_request.user,
                "response_text": response.text,
            }
            try:
                parsed = schema.model_validate(json.loads(_extract_json(response.text)))
            except (ValueError, ValidationError) as exc:
                obs.finish("invalid_json", **facts)  # type: ignore[arg-type]
                if remaining == 0:
                    raise StructuredOutputError(
                        f"model output does not match {schema.__name__}"
                    ) from exc
                problem = str(exc).splitlines()[0][:300]
                attempt = request.model_copy(
                    update={
                        "user": f"{request.user}\n\nYour previous reply was invalid ({problem}). "
                        "Reply with only the JSON object."
                    }
                )
                continue
            obs.finish("repaired" if number > 1 else "ok", **facts)  # type: ignore[arg-type]
            return parsed, response
    raise AssertionError("unreachable")  # pragma: no cover


class PriceTable(BaseModel):
    """USD per million tokens; configure per model. Unknown models cost 0 and are flagged."""

    prices: dict[str, tuple[float, float]] = Field(default_factory=dict)

    def cost(self, model: str, usage: ModelUsage) -> float:
        input_price, output_price = self.prices.get(model, (0.0, 0.0))
        return (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000


class ScriptedModelProvider:
    """Returns pre-recorded outputs in order (tests, calibration, replay)."""

    name = "scripted"

    def __init__(self, outputs: Sequence[str], *, model: str = "scripted-1") -> None:
        self.model = model
        self._outputs = list(outputs)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        started = time.perf_counter()
        text = self._outputs.pop(0) if self._outputs else ""
        usage = ModelUsage(
            input_tokens=len((request.system + request.untrusted_context + request.user).split()),
            output_tokens=len(text.split()),
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return ModelResponse(text=text, model=self.model, provider=self.name, usage=usage)
