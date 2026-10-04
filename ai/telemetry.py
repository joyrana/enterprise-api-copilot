"""Telemetry facade.

* Forwards spans to the OpenTelemetry API when it is installed (no-op tracer otherwise).
* Optionally records spans in-process (``SpanRecorder``) for tests and evaluation.
* GenAI attribute names live here only, because the OTel GenAI conventions are still
  ``development`` stability (see docs/architecture/technology-baseline.md).
* Attributes must be scalars describing sizes, counts, ids and outcomes. Payloads,
  prompts and tokens are never recorded; ``set`` drops string values longer than
  ``MAX_ATTR_LEN`` as a guard against accidentally attaching content.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

_otel_trace: Any
try:  # optional dependency
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - exercised only without opentelemetry-api
    _otel_trace = None

MAX_ATTR_LEN = 256
_trace_log = logging.getLogger("copilot.trace")

# GenAI semantic convention names (development stability) — single place to rename.
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_PROVIDER = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"

Scalar = str | int | float | bool


# ── W3C trace context ───────────────────────────────────────────────────────
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str

    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-01"


_current: ContextVar[TraceContext | None] = ContextVar("copilot_trace", default=None)


def parse_traceparent(header: str | None) -> TraceContext | None:
    """Accept only well-formed W3C traceparent values (all-zero ids are invalid)."""
    m = _TRACEPARENT.match((header or "").strip().lower())
    if not m or m.group(1) == "0" * 32 or m.group(2) == "0" * 16:
        return None
    return TraceContext(m.group(1), m.group(2))


def current_trace() -> TraceContext | None:
    return _current.get()


@contextmanager
def trace_scope(parent: TraceContext | None = None) -> Iterator[TraceContext]:
    """Start (or continue, from an incoming traceparent) a trace for one request."""
    ctx = TraceContext(parent.trace_id if parent else secrets.token_hex(16), secrets.token_hex(8))
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def outbound_traceparent() -> str | None:
    """Header value for an outbound call made inside the current span."""
    ctx = _current.get()
    return ctx.traceparent() if ctx else None


@dataclass
class RecordedSpan:
    name: str
    attributes: dict[str, Scalar] = field(default_factory=dict)
    start: float = 0.0
    end: float = 0.0
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str | None = None

    @property
    def duration_ms(self) -> float:
        return (self.end - self.start) * 1000

    def as_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "duration_ms": round(self.duration_ms, 3),
                "attributes": self.attributes,
            },
            sort_keys=True,
        )


class SpanRecorder:
    def __init__(self) -> None:
        self.spans: list[RecordedSpan] = []

    def named(self, name: str) -> list[RecordedSpan]:
        return [s for s in self.spans if s.name == name]


class SpanHandle:
    def __init__(self, recorded: RecordedSpan, otel_span: Any) -> None:
        self._recorded = recorded
        self._otel = otel_span

    def set(self, key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and len(value) > MAX_ATTR_LEN:
            return
        if not isinstance(value, str | int | float | bool):
            return
        self._recorded.attributes[key] = value
        if self._otel is not None:
            self._otel.set_attribute(key, value)


class Telemetry:
    """Spans with W3C ids; optional JSON-lines export on the ``copilot.trace`` logger
    (``json_export=True`` or ``COPILOT_TRACE_JSON=1``) for a local observability profile
    without an OpenTelemetry SDK. Exported spans carry ids, durations and the same
    scalar-only attributes as above — never payloads or tokens."""

    def __init__(
        self,
        recorder: SpanRecorder | None = None,
        tracer_name: str = "copilot",
        *,
        json_export: bool | None = None,
    ) -> None:
        self.recorder = recorder
        self._tracer = _otel_trace.get_tracer(tracer_name) if _otel_trace is not None else None
        self.json_export = (
            os.environ.get("COPILOT_TRACE_JSON") == "1" if json_export is None else json_export
        )

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[SpanHandle]:
        parent = _current.get()
        ctx = TraceContext(
            parent.trace_id if parent else secrets.token_hex(16), secrets.token_hex(8)
        )
        recorded = RecordedSpan(
            name=name,
            start=time.perf_counter(),
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
            parent_span_id=parent.span_id if parent else None,
        )
        token = _current.set(ctx)
        otel_cm = (
            self._tracer.start_as_current_span(name)
            if self._tracer is not None
            else nullcontext(None)
        )
        try:
            with otel_cm as otel_span:
                handle = SpanHandle(recorded, otel_span)
                for key, value in attributes.items():
                    handle.set(key, value)
                yield handle
        finally:
            _current.reset(token)
            recorded.end = time.perf_counter()
            if self.recorder is not None:
                self.recorder.spans.append(recorded)
            if self.json_export:
                _trace_log.info(recorded.as_json())
