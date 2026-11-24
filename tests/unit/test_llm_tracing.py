"""G7: one ``llm.generate`` span per model call, prompt versions in run events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import Orchestrator
from ai.models.observe import PAYLOAD_ENV, PAYLOAD_FILE_ENV
from ai.telemetry import SpanRecorder, Telemetry
from tests.support import build_harness
from tests.unit.test_llm_agent import DEV, FINISH, Unreachable, call, intent, reply
from tests.unit.test_llm_secrets import JWT, LEAKY, Recorder


async def _discovery(llm: Recorder, recorder: SpanRecorder, query: str) -> object:
    h = build_harness()
    orchestrator = Orchestrator(h.services.runtime, llm=llm, telemetry=Telemetry(recorder))
    return await orchestrator.run(query, principal=DEV, environment="sandbox")


async def test_each_model_call_is_a_span_under_the_run_span() -> None:
    recorder = SpanRecorder()
    llm = Recorder(
        [
            "not json",  # intent attempt 1 is invalid -> repaired on attempt 2
            intent("api_discovery"),
            call("api.search", query="track a shipment"),
            FINISH,
            reply("Use `getShipmentTracking`.", ("operation_list", "search")),
        ]
    )
    state = await _discovery(llm, recorder, "which endpoint tracks a shipment?")
    assert state.status is RunStatus.COMPLETED  # type: ignore[attr-defined]
    run_span = recorder.named("agent.run")[0]
    spans = recorder.named("llm.generate")
    assert len(spans) == 5 and all(s.parent_span_id == run_span.span_id for s in spans)
    assert all(s.trace_id == run_span.trace_id for s in spans)
    assert [s.attributes["copilot.llm.stage"] for s in spans] == [
        "intent",
        "intent",
        "plan",
        "plan",
        "respond",
    ]
    assert [s.attributes["copilot.llm.outcome"] for s in spans] == [
        "invalid_json",
        "repaired",
        "ok",
        "ok",
        "ok",
    ]
    first = spans[0].attributes
    assert first["gen_ai.provider.name"] == "scripted"
    assert first["gen_ai.request.model"] == "scripted-1"
    assert first["copilot.llm.prompt_version"] == "intent-v3"
    assert first["copilot.llm.attempt"] == 1 and spans[1].attributes["copilot.llm.attempt"] == 2
    assert (
        isinstance(first["gen_ai.usage.input_tokens"], int)
        and first["gen_ai.usage.input_tokens"] > 0
    )
    assert "copilot.llm.latency_ms" in first
    # Only scalars: no prompt or response text on any span.
    assert not any("which endpoint" in str(v) for s in spans for v in s.attributes.values())


async def test_prompt_versions_are_recorded_in_run_events() -> None:
    recorder = SpanRecorder()
    llm = Recorder([intent("api_discovery"), call("api.search", query="x"), FINISH, reply("ok")])
    state = await _discovery(llm, recorder, "find an api")
    events = [e.detail for e in state.events if e.kind == "model_call"]  # type: ignore[attr-defined]
    assert [(e["stage"], e["prompt_version"], e["outcome"]) for e in events] == [
        ("intent", "intent-v3", "ok"),
        ("plan", "planner-v4", "ok"),
        ("plan", "planner-v4", "ok"),
        ("respond", "responder-v2", "ok"),
    ]


async def test_unavailable_model_is_an_unavailable_span() -> None:
    recorder = SpanRecorder()
    h = build_harness()
    orchestrator = Orchestrator(
        h.services.runtime, llm=Unreachable(), telemetry=Telemetry(recorder)
    )
    state = await orchestrator.run("anything at all", principal=DEV, environment="sandbox")
    assert state.status is RunStatus.FAILED
    [span] = recorder.named("llm.generate")
    assert span.attributes["copilot.llm.outcome"] == "unavailable"


async def test_payload_capture_is_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "payloads.jsonl"
    monkeypatch.setenv(PAYLOAD_FILE_ENV, str(target))
    monkeypatch.delenv(PAYLOAD_ENV, raising=False)
    llm = Recorder([intent("api_discovery"), call("api.search", query="x"), FINISH, reply("ok")])
    await _discovery(llm, SpanRecorder(), "find an api")
    assert not target.exists()


async def test_payload_capture_is_redacted_and_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "payloads.jsonl"
    monkeypatch.setenv(PAYLOAD_FILE_ENV, str(target))
    monkeypatch.setenv(PAYLOAD_ENV, "1")
    llm = Recorder(
        [
            intent("api_discovery"),
            call("api.search", query="x"),
            FINISH,
            reply("Here is the secret " + LEAKY + " " + "z" * 20000),
        ]
    )
    await _discovery(llm, SpanRecorder(), f"find an api {LEAKY}")
    text = target.read_text(encoding="utf-8")
    lines = [json.loads(line) for line in text.splitlines()]
    assert len(lines) == 4 and {line["stage"] for line in lines} == {"intent", "plan", "respond"}
    assert JWT not in text and "AKIAIOSFODNN7EXAMPLE" not in text and "s3cr3tpass" not in text
    assert all(len(line["request"]) <= 6000 and len(line["response"]) <= 6000 for line in lines)
    llm.assert_clean()
