"""Model-call observability (G7): one ``llm.generate`` span per provider call.

``generate_structured`` is the single path every agent stage takes, so it is also the
single place a call is observed. The orchestrator opens a scope (``llm_scope``) that
carries its :class:`Telemetry` and a list that collects one record per call; those records
become ``model_call`` run events, which is how ``prompt_version`` reaches run views.

Span attributes are scalars only (stage, provider, model, prompt version, token counts,
latency, outcome). Payload capture is opt-in (``COPILOT_LLM_TRACE_PAYLOADS=1``): redacted,
size-capped lines appended to a local file, never to spans or logs.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from ai.telemetry import (
    GEN_AI_INPUT_TOKENS,
    GEN_AI_OPERATION,
    GEN_AI_OUTPUT_TOKENS,
    GEN_AI_PROVIDER,
    GEN_AI_REQUEST_MODEL,
    SpanHandle,
    Telemetry,
)
from skills.runtime.redaction import redact_text

PAYLOAD_ENV = "COPILOT_LLM_TRACE_PAYLOADS"
PAYLOAD_FILE_ENV = "COPILOT_LLM_TRACE_FILE"
DEFAULT_PAYLOAD_FILE = ".copilot/llm-payloads.jsonl"
MAX_PAYLOAD_CHARS = 6000

OUTCOMES = ("ok", "repaired", "invalid_json", "unavailable")

_scope: ContextVar[tuple[Telemetry, list[dict[str, Any]]] | None] = ContextVar(
    "copilot_llm_scope", default=None
)
_tenant: ContextVar[str] = ContextVar("copilot_llm_tenant", default="-")
_queue_wait: ContextVar[list[float] | None] = ContextVar("copilot_llm_queue_wait", default=None)
_file_lock = threading.Lock()


def current_tenant() -> str:
    """Tenant of the run making model calls (for fair queuing)."""
    return _tenant.get()


def record_queue_wait(seconds: float) -> None:
    """Called by the model limiter: how long this call waited for a slot."""
    sink = _queue_wait.get()
    if sink is not None:
        sink.append(seconds)


def drain_queue_wait() -> float:
    """Seconds spent waiting for a model slot since the last drain (this run's scope)."""
    sink = _queue_wait.get()
    if not sink:
        return 0.0
    total = sum(sink)
    sink.clear()
    return total


@contextmanager
def llm_scope(telemetry: Telemetry, tenant: str = "-") -> Iterator[list[dict[str, Any]]]:
    """Observe model calls made inside the block; yields the list their records land in."""
    records: list[dict[str, Any]] = []
    token = _scope.set((telemetry, records))
    tenant_token = _tenant.set(tenant)
    wait_token = _queue_wait.set([])
    try:
        yield records
    finally:
        _scope.reset(token)
        _tenant.reset(tenant_token)
        _queue_wait.reset(wait_token)


def payload_capture_enabled() -> bool:
    return os.environ.get(PAYLOAD_ENV) == "1"


def _capture(record: dict[str, Any], request_text: str, response_text: str) -> None:
    if not payload_capture_enabled():
        return
    path = Path(os.environ.get(PAYLOAD_FILE_ENV) or DEFAULT_PAYLOAD_FILE)
    line = {
        **record,
        "request": redact_text(request_text)[:MAX_PAYLOAD_CHARS],
        "response": redact_text(response_text)[:MAX_PAYLOAD_CHARS],
    }
    with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")


class CallObservation:
    """Context for one provider call; ``finish`` records the outcome exactly once."""

    def __init__(self, stage: str, prompt_version: str, attempt: int) -> None:
        self.stage, self.prompt_version, self.attempt = stage, prompt_version, attempt
        self.started = time.perf_counter()
        self._span: SpanHandle | None = None
        self.record: dict[str, Any] = {}

    def bind(self, span: SpanHandle) -> None:
        self._span = span
        span.set(GEN_AI_OPERATION, "chat")
        span.set("copilot.llm.stage", self.stage)
        span.set("copilot.llm.prompt_version", self.prompt_version)
        span.set("copilot.llm.attempt", self.attempt)

    def finish(
        self,
        outcome: str,
        *,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float | None = None,
        request_text: str = "",
        response_text: str = "",
    ) -> None:
        latency = (
            latency_ms if latency_ms is not None else (time.perf_counter() - self.started) * 1000
        )
        self.record = {
            "stage": self.stage,
            "provider": provider,
            "model": model,
            "prompt_version": self.prompt_version,
            "attempt": self.attempt,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency, 2),
            "outcome": outcome,
        }
        if self._span is not None:
            self._span.set(GEN_AI_PROVIDER, provider)
            self._span.set(GEN_AI_REQUEST_MODEL, model)
            self._span.set(GEN_AI_INPUT_TOKENS, input_tokens)
            self._span.set(GEN_AI_OUTPUT_TOKENS, output_tokens)
            self._span.set("copilot.llm.latency_ms", round(latency, 2))
            self._span.set("copilot.llm.outcome", outcome)
        active = _scope.get()
        if active is not None:
            active[1].append(self.record)
        _capture(self.record, request_text, response_text)


@contextmanager
def observe_call(stage: str, prompt_version: str, attempt: int) -> Iterator[CallObservation]:
    """A ``llm.generate`` span (when a scope is active) around one provider call."""
    obs = CallObservation(stage, prompt_version, attempt)
    active = _scope.get()
    if active is None:
        yield obs
        return
    with active[0].span("llm.generate") as span:
        obs.bind(span)
        yield obs
