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


def test_every_documented_operation_was_exercised() -> None:
    assert CONTRACT.operations() - CONTRACT.covered == set()
