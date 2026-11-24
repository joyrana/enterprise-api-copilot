"""The agent_llm evaluation harness itself: scoring, gates and the committed replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.models.base import ScriptedModelProvider
from evals import agent_llm
from tests.unit.test_llm_agent import call, intent


def _case(case_id: str) -> dict[str, Any]:
    [case] = agent_llm.load_cases({case_id})
    return case


async def test_a_scripted_write_case_is_scored_and_stays_safe() -> None:
    case = _case("l-021")
    provider = ScriptedModelProvider(
        [
            intent("api_execution", amount_minor=50000, currency="INR", customer_id="cust_acm0001"),
            call("api.search", query="create a payment"),
            call("api.describe", operation_id="createPayment"),
            call("api.call.write", operation_id="createPayment", body={}),
        ]
    )
    provider.requests = []
    result = await agent_llm.run_case(case, provider, live=False, replay_latency_ms=1234.0)
    assert result["success"], result
    assert result["status"] == "AWAITING_APPROVAL" and result["safety_violations"] == []
    assert result["skill_tp_fp_fn"] == [3, 0, 0] and result["latency_ms"] == 1234.0
    assert result["arguments"]["body"] == {
        "amount": 50000,
        "currency": "INR",
        "customer_id": "cust_acm0001",
    }
    agg = agent_llm.aggregate([result])
    assert agg["intent_accuracy"]["mean"] == 1.0 and agg["safety_violations"] == {}


async def test_ungrounded_model_values_are_counted_not_bound() -> None:
    case = _case("l-021")
    provider = ScriptedModelProvider(
        [
            intent("api_execution", amount_minor=50000, currency="INR", customer_id="cust_acm0001"),
            call("api.search", query="create a payment"),
            call("api.describe", operation_id="createPayment"),
            call(
                "api.call.write",
                operation_id="createPayment",
                body={"amount": 1, "currency": "INR", "customer_id": "cust_evil999"},
            ),
        ]
    )
    result = await agent_llm.run_case(case, provider, live=False, replay_latency_ms=0.0)
    assert result["dropped_values"] >= 1 and result["checks"]["arguments"]
    assert agent_llm.aggregate([result])["grounding_drop_rate"]["mean"] == 1.0


def test_gate_fails_on_safety_violations_and_regressions() -> None:
    base = {
        "intent_accuracy": {"mean": 0.9},
        "status_accuracy": {"mean": 0.9},
        "argument_exact_match": {"mean": 0.9},
        "skill_prf": {"f1": 0.9},
        "model_calls_per_run": {"mean": 5.0},
        "latency_ms": {"p95": 1000},
    }
    report: dict[str, Any] = {
        "mode": "replay",
        "notes": [],
        "aggregates": {**base, "safety_violations": {}},
    }
    assert agent_llm.gate(report, base) == []
    worse = {**report["aggregates"], "intent_accuracy": {"mean": 0.7}}
    assert any(
        "intent_accuracy" in f for f in agent_llm.gate({**report, "aggregates": worse}, base)
    )
    unsafe = {**report["aggregates"], "safety_violations": {"secret_leak": 1}}
    assert agent_llm.gate({**report, "aggregates": unsafe}, None) == ["safety: secret_leak x1"]
    diverged = {**report, "notes": ["l-001: replay diverged from the recording"]}
    assert agent_llm.gate(diverged, None)


async def test_committed_replay_has_no_safety_violations_and_matches_the_baseline() -> None:
    report = await agent_llm.run_suite("replay", record=False, only=None, model=None)
    assert report["aggregates"]["n"] >= 30, report["notes"]
    baseline = json.loads(
        (
            Path(agent_llm.__file__).parents[1] / "docs/evaluation/agent_llm_baseline.json"
        ).read_text()
    )
    assert agent_llm.gate(report, baseline) == []
    assert report["aggregates"]["safety_violations"] == {}
    assert (
        report["provenance"]["config"]["model"] and report["provenance"]["config"]["dataset_sha256"]
    )
