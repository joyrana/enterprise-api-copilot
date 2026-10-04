"""Trace correlation: incoming traceparent → agent/skill spans → outbound gateway call."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from starlette.testclient import TestClient

from ai.agent.orchestrator import InMemoryCheckpointStore
from ai.api.platform_app import PlatformConfig, create_platform_app
from ai.telemetry import SpanRecorder, Telemetry, parse_traceparent, trace_scope
from tests.support import build_harness

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
INCOMING = f"00-{TRACE}-00f067aa0ba902b7-01"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "garbage",
        f"00-{'0' * 32}-00f067aa0ba902b7-01",
        f"00-{TRACE}-{'0' * 16}-01",
        f"01-{TRACE}",
    ],
)
def test_invalid_traceparent_is_ignored(header: str) -> None:
    assert parse_traceparent(header) is None


def test_spans_nest_and_export_json(caplog: pytest.LogCaptureFixture) -> None:
    recorder = SpanRecorder()
    telemetry = Telemetry(recorder, json_export=True)
    with caplog.at_level(logging.INFO, logger="copilot.trace"):
        with trace_scope(parse_traceparent(INCOMING)):
            with telemetry.span("outer"):
                with telemetry.span(
                    "inner", **{"gen_ai.tool.name": "api.search", "body": "x" * 999}
                ):
                    pass
    inner, outer = recorder.spans
    assert inner.trace_id == outer.trace_id == TRACE and inner.parent_span_id == outer.span_id
    exported = [json.loads(r.getMessage()) for r in caplog.records]
    assert exported[0]["name"] == "inner" and exported[0]["attributes"] == {
        "gen_ai.tool.name": "api.search"
    }


def test_trace_flows_from_api_request_to_gateway_call() -> None:
    seen: list[str | None] = []
    h = build_harness()
    original = h.services.gateway._http._transport

    class Spy(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if not request.url.path.startswith("/oauth"):
                seen.append(request.headers.get("traceparent"))
            return await original.handle_async_request(request)  # type: ignore[union-attr]

    h.services.gateway._http._transport = Spy()
    app = create_platform_app(h.services, PlatformConfig(run_store=InMemoryCheckpointStore()))
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/dev-token", json={"subject": "alice"}).json()[
            "access_token"
        ]
        response = client.post(
            "/api/v1/runs",
            json={"query": "List customers"},
            headers={"Authorization": f"Bearer {token}", "traceparent": INCOMING},
        )
    assert response.status_code == 201
    assert response.headers["traceparent"].split("-")[1] == TRACE
    assert seen and all(tp is not None and tp.split("-")[1] == TRACE for tp in seen)
    run_spans = [s for s in h.recorder.spans if s.name in {"agent.run", "skill.invoke"}]
    assert run_spans and {s.trace_id for s in run_spans} == {TRACE}
