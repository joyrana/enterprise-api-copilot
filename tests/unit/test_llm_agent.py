"""Agentic mode: LLM intent → resolved skills → LLM step loop → LLM response + UI.

Model outputs are scripted, so these tests pin the *guarantees* around the model —
resolution, validation, grounding, approval and UI construction — not model quality.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from ai.agent.contracts import Intent, RunStatus
from ai.agent.intent_llm import LLMIntentClassifier
from ai.agent.orchestrator import FileCheckpointStore, Orchestrator
from ai.agent.ui import REGISTRY
from ai.models.base import ModelRequest, ModelResponse, ModelUnavailableError, ScriptedModelProvider
from ai.models.mlx_server import MLXServerProvider
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
from skills.runtime.policy import LocalPolicyEngine
from tests.support import build_harness

DEV = Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"}))
APPROVER = Principal(subject="priya", tenant_id="acme", roles=frozenset({"approver"}))
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi" / "platform-api.yaml"


def intent(name: str, **entities: Any) -> str:
    return json.dumps(
        {"intent": name, "confidence": 0.9, "rationale": "scripted", "entities": entities}
    )


def call(skill_id: str, **arguments: Any) -> str:
    return json.dumps(
        {"thought": "next", "action": "call", "skill_id": skill_id, "arguments": arguments}
    )


FINISH = json.dumps({"thought": "done", "action": "finish", "skill_id": "", "arguments": {}})


def reply(message: str, *components: tuple[str, str]) -> str:
    return json.dumps(
        {"message": message, "components": [{"component": c, "source": s} for c, s in components]}
    )


def tool_skills(state: Any) -> list[str]:
    return [e.detail["skill_id"] for e in state.events if e.kind == "tool_call"]


class Unreachable:
    name = "mlx"
    model = "mlx-community/Qwen3-4B-Instruct-2507-4bit"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise ModelUnavailableError("connection refused")


async def test_agentic_discovery_builds_ui_from_real_output() -> None:
    h = build_harness()
    llm = ScriptedModelProvider(
        [
            intent("api_discovery", operation_hint="track a shipment"),
            call("api.search", query="track a shipment"),
            FINISH,
            reply(
                "Use `getShipmentTracking`.",
                ("operation_list", "search"),
                ("approval_request", ""),  # server-controlled: never selectable
                ("code_snippets", "search"),  # wrong source skill
            ),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        "which endpoint tracks a shipment?", principal=DEV, environment="sandbox"
    )
    assert state.mode == "agentic" and state.status is RunStatus.COMPLETED
    assert state.message == "Use `getShipmentTracking`."
    assert state.allowed_skills == ["api.search", "api.describe"]
    assert [c.component for c in state.ui] == ["operation_list"]
    ops = [o["operation_id"] for o in state.ui[0].props["operations"]]
    assert "getShipmentTracking" in ops  # props come from the real search result
    ui_event = next(e for e in state.events if e.kind == "ui")
    assert ui_event.detail["chosen_by"] == "model" and len(ui_event.detail["rejected"]) == 2
    assert state.model_usage and state.model_usage.calls == 4 and state.evidence


async def test_planner_cannot_reach_skills_outside_the_resolved_set() -> None:
    h = build_harness()
    llm = ScriptedModelProvider(
        [
            intent("docs_question"),
            call(
                "api.call.write",
                operation_id="createPayment",
                body={"amount": 50000, "currency": "INR", "customer_id": "cust_acm0001"},
            ),
            call("docs.search", query="minimum payment amount"),
            FINISH,
            # "1" is a citation marker, not a step: resolved to the only docs.search step.
            reply("The minimum is 100 minor units [1].", ("doc_sources", "1")),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        "What is the minimum payment amount?", principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.COMPLETED
    assert tool_skills(state) == ["docs.search"]
    assert [(c.component, c.source) for c in state.ui] == [("doc_sources", "docs")]
    rejected = [e for e in state.events if e.kind == "plan_rejected"]
    assert rejected and "not available" in rejected[0].detail["reason"]
    assert len(h.app.state.sandbox.tenant("acme").payments) == 3


async def test_execution_is_validated_grounded_and_resumed_after_approval(tmp_path: Path) -> None:
    h = build_harness()
    store = FileCheckpointStore(tmp_path)
    query = "Create a sandbox payment of ₹500 for customer cust_acm0001"
    llm = ScriptedModelProvider(
        [
            intent("api_execution", amount_minor=50000, currency="INR"),
            call("api.call.write", operation_id="createPayment", body={}),  # no describe yet
            call("api.search", query="create a payment"),
            call("api.describe", operation_id="createPayment"),
            call("api.call.read", operation_id="createPayment"),  # wrong invocation skill
            call(
                "api.call.write",
                operation_id="createPayment",
                # 500 is not the minor-unit amount and cust_evil999 was never mentioned.
                body={"amount": 500, "currency": "INR", "customer_id": "cust_evil999"},
            ),
            FINISH,
            reply("Payment created.", ("api_response", "call"), ("run_trace", "")),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm, checkpoints=store).run(
        query, principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.AWAITING_APPROVAL and state.pending_approval
    summary = state.pending_approval.summary
    assert '"amount": 50000' in summary and "cust_acm0001" in summary
    assert "cust_evil999" not in summary
    reasons = [e.detail["reason"] for e in state.events if e.kind == "plan_rejected"]
    assert any("describe" in r for r in reasons) and any("api.call.write" in r for r in reasons)
    grounded = next(e for e in state.events if e.kind == "arguments_grounded")
    assert "body.customer_id" in grounded.detail["dropped"]
    assert "body.amount" in grounded.detail["overridden"]
    assert state.ui[-1].component == "approval_request"
    assert len(h.app.state.sandbox.tenant("acme").payments) == 3

    token = await ApprovalService(h.services.approval_signer, LocalPolicyEngine()).approve(
        approver=APPROVER,
        action_hash=state.pending_approval.action_hash,
        tenant_id="acme",
        environment="sandbox",
    )
    resumed = await Orchestrator(h.services.runtime, llm=llm, checkpoints=store).resume(
        state.run_id, approval_token=token
    )
    assert resumed.status is RunStatus.COMPLETED, resumed.message
    assert resumed.mode == "agentic" and resumed.message == "Payment created."
    assert [c.component for c in resumed.ui] == ["api_response", "run_trace"]
    assert resumed.ui[0].props["status_code"] == 201
    assert len(h.app.state.sandbox.tenant("acme").payments) == 4


async def test_ungrounded_required_values_ask_the_user() -> None:
    h = build_harness()
    llm = ScriptedModelProvider(
        [
            intent("api_execution", customer_id="cust_acm0001"),
            call("api.search", query="create a payment"),
            call("api.describe", operation_id="createPayment"),
            call(
                "api.call.write",
                operation_id="createPayment",
                body={"amount": 50000, "currency": "INR", "customer_id": "cust_acm0001"},
            ),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        "Create a payment for customer cust_acm0001", principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.NEEDS_CLARIFICATION
    assert set(state.missing_fields) == {"body.amount", "body.currency"}
    assert state.ui[-1].component == "clarification"
    assert "api.call.write" not in tool_skills(state)


async def test_jwt_placeholder_is_substituted_and_never_shown() -> None:
    h = build_harness()

    def b64(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    jwt = f"{b64({'alg': 'HS256'})}.{b64({'scope': 'payments:read', 'exp': 1700000000})}.sig0abc"
    llm = ScriptedModelProvider(
        [
            intent("token_inspection"),
            call("token.inspect", token="$JWT"),
            FINISH,
            reply("The token has expired.", ("jwt_report", "inspect")),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        f"inspect this token {jwt}", principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.COMPLETED and state.ui[0].component == "jwt_report"
    assert state.ui[0].props["expired"] is True
    sent = "".join(r.user + r.untrusted_context for r in llm.requests[1:])
    assert jwt not in sent and "<JWT>" in sent


async def test_unreachable_model_fails_the_run_without_rules_fallback() -> None:
    h = build_harness()
    state = await Orchestrator(h.services.runtime, llm=Unreachable()).run(
        "which endpoint tracks a shipment?", principal=DEV, environment="sandbox"
    )
    assert state.mode == "agentic" and state.status is RunStatus.FAILED
    assert "unavailable" in state.message and "getShipmentTracking" not in state.message
    assert state.intent is None and state.tool_calls == 0 and state.ui == []
    assert state.model_usage and state.model_usage.failures == 1
    failed = [e for e in state.events if e.kind == "model_failed"]
    assert failed and failed[0].detail["stage"] == "intent"


class FailsAfter:
    """Answers the first ``n`` calls from a script, then becomes unreachable."""

    name = "mlx"
    model = "mlx-community/Qwen3-4B-Instruct-2507-4bit"

    def __init__(self, outputs: list[str]) -> None:
        self._scripted = ScriptedModelProvider(outputs)
        self._left = len(outputs)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if self._left == 0:
            raise ModelUnavailableError("connection refused")
        self._left -= 1
        return await self._scripted.generate(request)


async def test_model_lost_mid_run_fails_but_shows_completed_steps() -> None:
    h = build_harness()
    llm = FailsAfter([intent("api_discovery"), call("api.search", query="track a shipment")])
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        "which endpoint tracks a shipment?", principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.FAILED and "unavailable" in state.message
    assert "1 step(s) had already run" in state.message
    assert [c.component for c in state.ui] == ["operation_list"]  # real search output
    assert next(e for e in state.events if e.kind == "model_failed").detail["stage"] == "plan"


async def test_responder_failure_fails_instead_of_using_the_template_reply() -> None:
    h = build_harness()
    llm = FailsAfter(
        [intent("api_discovery"), call("api.search", query="track a shipment"), FINISH]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        "which endpoint tracks a shipment?", principal=DEV, environment="sandbox"
    )
    assert state.status is RunStatus.FAILED and "unavailable" in state.message
    assert next(e for e in state.events if e.kind == "model_failed").detail["stage"] == "respond"
    assert state.model_usage and state.model_usage.calls == 3
    assert state.model_usage.failures == 1


async def test_llm_entities_are_grounded_in_the_request() -> None:
    llm = ScriptedModelProvider(
        [intent("api_execution", payment_id="pay_invented0001", order_id="ord_A1B2")]
    )
    classifier = LLMIntentClassifier(llm)
    result = await classifier.aclassify("Track order ord_A1B2 please")
    assert result.intent is Intent.API_EXECUTION
    assert result.entities.order_id == "ord_A1B2" and result.entities.payment_id is None
    assert classifier.dropped_entities == ["payment_id"]
    assert "ord_A1B2" in llm.requests[0].user


async def test_mlx_provider_sends_openai_compatible_request() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '<think>\n\n</think>\n\n{"ok": true}',
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    provider = MLXServerProvider(transport=httpx.MockTransport(handler))
    response = await provider.generate(
        ModelRequest(
            task="plan",
            system="trusted",
            untrusted_context="doc text",
            user="question",
            prompt_version="v",
            json_schema={"type": "object"},
        )
    )
    assert response.text == '{"ok": true}' and response.usage.output_tokens == 3
    assert seen["url"] == "http://127.0.0.1:8000/v1/chat/completions"
    assert seen["model"] == "mlx-community/Qwen3-4B-Instruct-2507-4bit" and seen["stream"] is False
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"}
    system, user = seen["messages"][0]["content"], seen["messages"][1]["content"]
    assert system.startswith("trusted") and '{"type":"object"}' in system
    assert "<untrusted_context>" in user and user.endswith("question")

    failing = MLXServerProvider(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ModelUnavailableError):
        await failing.generate(ModelRequest(task="t", system="s", user="u", prompt_version="v"))


async def test_malformed_json_is_repaired_once() -> None:
    llm = ScriptedModelProvider(["sure! here you go", intent("docs_question")])
    result = await LLMIntentClassifier(llm).aclassify("What is the minimum payment amount?")
    assert result.intent is Intent.DOCS_QUESTION and result.classifier.startswith("llm:")
    assert "previous reply was invalid" in llm.requests[1].user


def test_component_registry_matches_the_platform_contract() -> None:
    schema = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    enum = schema["components"]["schemas"]["UIComponent"]["properties"]["component"]["enum"]
    assert set(enum) == set(REGISTRY)
