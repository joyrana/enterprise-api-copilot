"""Internal agent-service API: service-to-service auth + contract conformance."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from ai.agent.orchestrator import InMemoryCheckpointStore
from ai.api.agent_app import create_agent_app, service_authority
from ai.api.auth import TokenAuthority
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
from skills.runtime.policy import LocalPolicyEngine
from tests.contract.openapi_contract import Contract
from tests.support import Harness, build_harness

CONTRACT = Contract("agent-service.yaml")
SERVICE_KEY = b"s" * 32
ALICE = Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"}))
GINA = Principal(subject="gina", tenant_id="globex", roles=frozenset({"developer"}))


@pytest.fixture(scope="module")
def env() -> Iterator[tuple[TestClient, Harness]]:
    h = build_harness()
    app = create_agent_app(h.services, service_key=SERVICE_KEY, store=InMemoryCheckpointStore())
    with TestClient(app) as client:
        yield client, h


def svc(principal: Principal) -> str:
    return service_authority(SERVICE_KEY).issue(principal)


def call(
    client: TestClient, method: str, path: str, token: str | None = None, **kw: Any
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return CONTRACT.check(client.request(method, path, headers=headers, **kw))


def test_health_is_public_runs_are_not(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    assert call(client, "GET", "/internal/v1/health").json()["status"] == "UP"
    assert (
        call(
            client, "POST", "/internal/v1/runs", json={"query": "x", "environment": "sandbox"}
        ).status_code
        == 401
    )


def test_user_tokens_and_long_lived_tokens_are_rejected(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    user_token = TokenAuthority(
        SERVICE_KEY, issuer="copilot-platform", audience="copilot-platform"
    ).issue(ALICE)
    assert (
        call(client, "GET", "/internal/v1/runs/run_0000000000000000", user_token).status_code == 401
    )
    long_lived = TokenAuthority(
        SERVICE_KEY, issuer="copilot-platform", audience="copilot-agent", max_ttl_s=7200
    ).issue(ALICE)
    assert (
        call(client, "GET", "/internal/v1/runs/run_0000000000000000", long_lived).status_code == 401
    )


def test_start_resume_and_isolation(env: tuple[TestClient, Harness]) -> None:
    client, h = env
    started = call(
        client,
        "POST",
        "/internal/v1/runs",
        svc(ALICE),
        json={
            "query": "Charge ₹300 to customer cust_acm0003 as a new payment",
            "environment": "sandbox",
        },
    )
    assert started.status_code == 201
    run = started.json()
    assert run["status"] == "AWAITING_APPROVAL", run["message"]
    assert call(client, "GET", f"/internal/v1/runs/{run['run_id']}", svc(GINA)).status_code == 404

    # The platform's approval service issues the token; the agent only forwards it.
    approver = Principal(subject="priya", tenant_id="acme", roles=frozenset({"approver"}))
    import asyncio

    token = asyncio.run(
        ApprovalService(h.services.approval_signer, LocalPolicyEngine()).approve(
            approver=approver,
            action_hash=run["pending_approval"]["action_hash"],
            tenant_id="acme",
            environment="sandbox",
        )
    )
    resumed = call(
        client,
        "POST",
        f"/internal/v1/runs/{run['run_id']}/resume",
        svc(ALICE),
        json={"approval_token": token},
    )
    assert resumed.status_code == 200 and resumed.json()["status"] == "COMPLETED"
    again = call(
        client,
        "POST",
        f"/internal/v1/runs/{run['run_id']}/resume",
        svc(ALICE),
        json={"approval_token": token},
    )
    assert again.status_code == 409
    assert (
        call(client, "GET", f"/internal/v1/runs/{run['run_id']}", svc(ALICE)).json()["status"]
        == "COMPLETED"
    )


def test_clarify_endpoint(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    started = call(
        client,
        "POST",
        "/internal/v1/runs",
        svc(ALICE),
        json={
            "query": "Create a payment for customer cust_acm0004",
            "environment": "sandbox",
            "conversation_id": "conv_0123456789abcdef",
        },
    )
    assert started.status_code == 404  # unknown conversation, even with a valid service token
    started = call(
        client,
        "POST",
        "/internal/v1/runs",
        svc(ALICE),
        json={"query": "Create a payment for customer cust_acm0004", "environment": "sandbox"},
    ).json()
    assert started["status"] == "NEEDS_CLARIFICATION"
    path = f"/internal/v1/runs/{started['run_id']}/clarify"
    assert call(client, "POST", path, svc(GINA), json={"message": "₹100"}).status_code == 404
    paused = call(client, "POST", path, svc(ALICE), json={"message": "₹100"}).json()
    assert paused["status"] == "AWAITING_APPROVAL"
    assert call(client, "POST", path, svc(ALICE), json={"message": "₹100"}).status_code == 409
    assert call(client, "POST", path, svc(ALICE), json={}).status_code == 400


def test_async_start_and_events(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    accepted = call(
        client,
        "POST",
        "/internal/v1/runs",
        svc(ALICE),
        params={"mode": "async"},
        json={"query": "which API lists customers?", "environment": "sandbox"},
    )
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    with client.stream(
        "GET",
        f"/internal/v1/runs/{run_id}/events",
        headers={"Authorization": f"Bearer {svc(ALICE)}"},
    ) as r:
        r.read()
    assert CONTRACT.check(r).status_code == 200 and "event: status" in r.text
    with client.stream(
        "GET",
        f"/internal/v1/runs/{run_id}/events",
        headers={"Authorization": f"Bearer {svc(GINA)}"},
    ) as other:
        other.read()
    assert CONTRACT.check(other).status_code == 404


def test_catalog_runs_conversations_and_reject(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    alice, gina = svc(ALICE), svc(GINA)
    assert {s["id"] for s in call(client, "GET", "/internal/v1/skills", alice).json()["skills"]}
    hits = call(
        client, "GET", "/internal/v1/apis/search", alice, params={"q": "refund a payment"}
    ).json()["results"]
    assert hits[0]["operation_id"] == "refundPayment"
    assert (
        call(client, "GET", "/internal/v1/apis/search", alice, params={"q": ""}).status_code == 400
    )
    assert call(client, "GET", "/internal/v1/apis/createPayment", alice).status_code == 200
    assert call(client, "GET", "/internal/v1/apis/nope", alice).status_code == 404

    conv = call(client, "POST", "/internal/v1/conversations", alice).json()
    cid = conv["conversation_id"]
    assert call(client, "GET", f"/internal/v1/conversations/{cid}", gina).status_code == 404
    assert call(client, "GET", f"/internal/v1/conversations/{cid}", alice).json()["runs"] == []

    run = call(
        client,
        "POST",
        "/internal/v1/runs",
        alice,
        json={
            "query": "Charge ₹100 to customer cust_acm0003 as a new payment",
            "environment": "sandbox",
        },
    ).json()
    assert run["status"] == "AWAITING_APPROVAL"
    listed = call(client, "GET", "/internal/v1/runs", alice, params={"status": "AWAITING_APPROVAL"})
    assert run["run_id"] in {r["run_id"] for r in listed.json()["runs"]}
    assert call(client, "GET", "/internal/v1/runs", gina).json()["runs"] == []
    assert call(client, "GET", "/internal/v1/runs", alice, params={"limit": 0}).status_code == 400
    path = f"/internal/v1/runs/{run['run_id']}/reject"
    assert call(client, "POST", path, gina, json={}).status_code == 404
    rejected = call(client, "POST", path, alice, json={"reason": "no"}).json()
    assert rejected["status"] == "REJECTED"
    assert call(client, "POST", path, alice, json={}).status_code == 409


def test_every_documented_operation_was_exercised() -> None:
    assert CONTRACT.operations() - CONTRACT.covered == set()
