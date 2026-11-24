"""Invariant 6: no credential reaches a model provider, at any stage, including retries."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import Orchestrator
from ai.agent.planner_llm import LLMStepPlanner
from ai.agent.responder import LLMResponder
from ai.models.base import ModelRequest, ScriptedModelProvider, generate_structured
from skills.runtime.contracts import Principal
from tests.support import build_harness
from tests.unit.test_llm_agent import FINISH, call, intent, reply

DEV = Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"}))


def _b64(obj: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


JWT = f"{_b64({'alg': 'HS256'})}.{_b64({'scope': 'payments:read'})}.sigsigsig"
SECRETS = {
    "jwt": JWT,
    "bearer": "Bearer abcdef0123456789token",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\n-----END PRIVATE KEY-----",
    "aws": "AKIAIOSFODNN7EXAMPLE",
    "github": "ghp_" + "a1B2c3D4e5" * 4,
    "provider_key": "sk-live-abcdefghijklmnop1234",
    "basic_url": "https://svc:s3cr3tpass@internal.example.com/x",
    "client_secret": "client_secret=zx9y8w7v6u5t",
}
# The unique secret material of each sample (what must never appear in a request).
NEEDLES = [
    JWT,
    "abcdef0123456789token",
    "MIIEvQIBADANBgkq",
    "AKIAIOSFODNN7EXAMPLE",
    "a1B2c3D4e5a1B2c3D4e5",
    "abcdefghijklmnop1234",
    "s3cr3tpass",
    "zx9y8w7v6u5t",
]
LEAKY = " ".join(SECRETS.values())


class Recorder(ScriptedModelProvider):
    def assert_clean(self) -> None:
        assert self.requests
        for request in self.requests:
            blob = request.system + request.untrusted_context + request.user
            for needle in NEEDLES:
                assert needle not in blob, f"{request.task} request leaked {needle[:12]}…"


async def test_every_stage_and_repair_retry_is_free_of_secrets() -> None:
    h = build_harness()
    llm = Recorder(
        [
            "not json",  # intent: forces the repair retry path
            intent("api_discovery"),
            call("api.search", query="track a shipment"),
            FINISH,
            reply("Use `getShipmentTracking`.", ("operation_list", "search")),
        ]
    )
    state = await Orchestrator(h.services.runtime, llm=llm).run(
        f"which endpoint tracks a shipment? context: {LEAKY}",
        principal=DEV,
        environment="sandbox",
    )
    assert state.status is RunStatus.COMPLETED
    assert {r.task for r in llm.requests} == {"intent", "plan", "respond"}
    assert sum(r.task == "intent" for r in llm.requests) == 2  # original + repair
    llm.assert_clean()
    assert "<JWT>" in llm.requests[0].user and "contains a JWT" in llm.requests[0].user


async def test_secrets_in_tool_output_do_not_reach_plan_or_respond_requests() -> None:
    h = build_harness()
    llm = Recorder([intent("api_discovery"), call("api.search", query="x"), FINISH, reply("ok")])
    orchestrator = Orchestrator(h.services.runtime, llm=llm)
    state = await orchestrator.run("find an api", principal=DEV, environment="sandbox")
    search = state.results["search"]
    state.results["search"] = search.model_copy(
        update={"output": {"results": [{"operation_id": LEAKY, "summary": LEAKY}], "note": LEAKY}}
    )
    llm._outputs += [FINISH, reply("ok")]
    assert state.intent is not None
    skills = list(orchestrator.resolver.resolve(state.intent.intent).skills)
    await LLMStepPlanner(llm).next_step(state, skills)
    await LLMResponder(llm).respond(state)
    llm.assert_clean()


@pytest.mark.parametrize("name", sorted(SECRETS))
async def test_sanitizer_masks_each_credential_shape(name: str) -> None:
    llm = Recorder(['{"v": 1}'])

    from pydantic import BaseModel

    class V(BaseModel):
        v: int

    await generate_structured(
        llm,
        ModelRequest(
            task="t",
            system=f"sys {SECRETS[name]}",
            untrusted_context=f"ctx {SECRETS[name]}",
            user=f"usr {SECRETS[name]}",
            prompt_version="v",
        ),
        V,
    )
    request = llm.requests[0]
    blob = request.system + request.untrusted_context + request.user
    assert SECRETS[name] not in blob
    assert ("<JWT>" if name == "jwt" else "[REDACTED]") in blob
