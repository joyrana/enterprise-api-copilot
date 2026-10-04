"""Platform API behaviour + contract conformance (contracts/openapi/platform-api.yaml)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from starlette.testclient import TestClient

from ai.agent.orchestrator import InMemoryCheckpointStore
from ai.api.platform_app import (
    PLATFORM_AUDIENCE,
    PLATFORM_ISSUER,
    PlatformConfig,
    create_platform_app,
)
from tests.contract.openapi_contract import Contract
from tests.support import Harness, build_harness

CONTRACT = Contract("platform-api.yaml")
KEY = b"p" * 32
WRITE = "Create a payment of ₹750 for customer cust_acm0002"


@pytest.fixture(scope="module")
def env() -> Iterator[tuple[TestClient, Harness]]:
    h = build_harness()
    app = create_platform_app(
        h.services, PlatformConfig(token_key=KEY, run_store=InMemoryCheckpointStore())
    )
    with TestClient(app) as client:
        yield client, h


def call(
    client: TestClient, method: str, path: str, token: str | None = None, **kw: Any
) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return CONTRACT.check(client.request(method, path, headers=headers, **kw))


def login(client: TestClient, subject: str) -> str:
    response = call(client, "POST", "/api/v1/auth/dev-token", json={"subject": subject})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def test_health_and_identity(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    assert call(client, "GET", "/api/v1/health").json()["status"] == "UP"
    unauth = call(client, "GET", "/api/v1/me")
    assert unauth.status_code == 401 and unauth.headers["WWW-Authenticate"] == "Bearer"
    assert (
        call(client, "POST", "/api/v1/auth/dev-token", json={"subject": "mallory"}).status_code
        == 403
    )
    me = call(client, "GET", "/api/v1/me", login(client, "alice")).json()
    assert me == {"subject": "alice", "tenant_id": "acme", "roles": ["developer"]}


def test_request_id_is_echoed_or_generated(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    r = call(client, "GET", "/api/v1/health", headers={"X-Request-Id": "req-abcdef123"})
    assert r.headers["X-Request-Id"] == "req-abcdef123"
    bad = call(client, "GET", "/api/v1/me", headers={"X-Request-Id": "<script>"})
    assert (
        bad.headers["X-Request-Id"].startswith("req_")
        and bad.json()["requestId"] == bad.headers["X-Request-Id"]
    )


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: jwt.encode(
            {
                "sub": "alice",
                "tenant_id": "acme",
                "roles": ["admin"],
                "iss": PLATFORM_ISSUER,
                "aud": PLATFORM_AUDIENCE,
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            b"x" * 32,
            algorithm="HS256",
        ),
        lambda: jwt.encode(
            {
                "sub": "alice",
                "tenant_id": "acme",
                "roles": ["admin"],
                "iss": PLATFORM_ISSUER,
                "aud": PLATFORM_AUDIENCE,
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 3600,
            },
            KEY,
            algorithm="HS256",
        ),
        lambda: jwt.encode(
            {
                "sub": "alice",
                "tenant_id": "acme",
                "roles": ["admin"],
                "iss": PLATFORM_ISSUER,
                "aud": "copilot-agent",
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            KEY,
            algorithm="HS256",
        ),
        lambda: jwt.encode(
            {
                "sub": "alice",
                "tenant_id": "acme",
                "roles": ["admin"],
                "iss": PLATFORM_ISSUER,
                "aud": PLATFORM_AUDIENCE,
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            None,
            algorithm="none",
        ),
        lambda: jwt.encode(
            {
                "sub": "alice",
                "iss": PLATFORM_ISSUER,
                "aud": PLATFORM_AUDIENCE,
                "iat": int(time.time()),
                "exp": int(time.time()) + 60,
            },
            KEY,
            algorithm="HS256",
        ),
        lambda: jwt.encode(
            {
                "sub": "alice",
                "tenant_id": "acme",
                "roles": ["admin"],
                "iss": PLATFORM_ISSUER,
                "aud": PLATFORM_AUDIENCE,
                "iat": int(time.time()),
                "exp": int(time.time()) + 999_999,
            },
            KEY,
            algorithm="HS256",
        ),
    ],
    ids=[
        "forged-key",
        "expired",
        "wrong-audience",
        "alg-none",
        "missing-claims",
        "lifetime-too-long",
    ],
)
def test_bad_tokens_are_rejected(env: tuple[TestClient, Harness], token_factory: Any) -> None:
    client, _ = env
    assert call(client, "GET", "/api/v1/me", token_factory()).status_code == 401


def test_catalog_endpoints(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    token = login(client, "vic")  # viewer: catalog read is allowed
    skills = call(client, "GET", "/api/v1/skills", token).json()["skills"]
    assert {s["id"] for s in skills} >= {"api.search", "api.call.write"}
    hits = call(
        client, "GET", "/api/v1/apis/search", token, params={"q": "refund a payment", "limit": 3}
    ).json()
    assert hits["results"][0]["operation_id"] == "refundPayment"
    op = call(client, "GET", "/api/v1/apis/createPayment", token).json()
    assert op["required_scopes"] == ["payments:write"] and op["side_effect"] == "WRITE"
    assert call(client, "GET", "/api/v1/apis/doesNotExist", token).status_code == 404
    assert call(client, "GET", "/api/v1/apis/search", token, params={"q": ""}).status_code == 400


def test_validation_and_size_limits(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    token = login(client, "alice")
    assert (
        call(
            client,
            "POST",
            "/api/v1/runs",
            token,
            json={"query": "x", "principal": {"roles": ["admin"]}},
        ).status_code
        == 400
    )
    assert call(client, "POST", "/api/v1/runs", token, json={"query": ""}).status_code == 400
    big = call(
        client,
        "POST",
        "/api/v1/runs",
        token,
        content=b'{"query":"' + b"a" * 70_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert big.status_code == 413


def test_run_approve_flow(env: tuple[TestClient, Harness]) -> None:
    client, h = env
    alice, priya = login(client, "alice"), login(client, "priya")
    before = len(h.app.state.sandbox.tenant("acme").payments)
    run = call(client, "POST", "/api/v1/runs", alice, json={"query": WRITE}).json()
    assert (
        run["status"] == "AWAITING_APPROVAL" and run["pending_approval"]["environment"] == "sandbox"
    )
    run_id, action = run["run_id"], run["pending_approval"]["action_hash"]

    pending = call(
        client, "GET", "/api/v1/runs", priya, params={"status": "AWAITING_APPROVAL"}
    ).json()["runs"]
    assert run_id in {r["run_id"] for r in pending}

    # The requester (developer) cannot approve; a mismatched hash is a conflict.
    assert (
        call(
            client, "POST", f"/api/v1/runs/{run_id}/approve", alice, json={"action_hash": action}
        ).status_code
        == 403
    )
    assert (
        call(
            client, "POST", f"/api/v1/runs/{run_id}/approve", priya, json={"action_hash": "0" * 64}
        ).status_code
        == 409
    )
    assert len(h.app.state.sandbox.tenant("acme").payments) == before

    done = call(
        client, "POST", f"/api/v1/runs/{run_id}/approve", priya, json={"action_hash": action}
    ).json()
    assert done["status"] == "COMPLETED" and "HTTP 201" in done["message"]
    assert {e["kind"] for e in done["timeline"]} >= {
        "created",
        "intent",
        "tool_call",
        "resumed",
        "approved",
    }
    assert len(h.app.state.sandbox.tenant("acme").payments) == before + 1
    assert (
        call(
            client, "POST", f"/api/v1/runs/{run_id}/approve", priya, json={"action_hash": action}
        ).status_code
        == 409
    )
    assert call(client, "GET", f"/api/v1/runs/{run_id}", alice).json()["status"] == "COMPLETED"


def test_reject_flow(env: tuple[TestClient, Harness]) -> None:
    client, h = env
    alice, priya, vic = login(client, "alice"), login(client, "priya"), login(client, "vic")
    before = len(h.app.state.sandbox.tenant("acme").payments)
    run = call(client, "POST", "/api/v1/runs", alice, json={"query": WRITE}).json()
    assert (
        call(client, "POST", f"/api/v1/runs/{run['run_id']}/reject", vic, json={}).status_code
        == 403
    )
    rejected = call(
        client, "POST", f"/api/v1/runs/{run['run_id']}/reject", priya, json={"reason": "not today"}
    ).json()
    assert rejected["status"] == "REJECTED" and rejected["pending_approval"] is None
    assert len(h.app.state.sandbox.tenant("acme").payments) == before


def test_tenant_isolation(env: tuple[TestClient, Harness]) -> None:
    client, _ = env
    alice, gina = login(client, "alice"), login(client, "gina")
    run = call(
        client, "POST", "/api/v1/runs", alice, json={"query": "which API lists customers?"}
    ).json()
    assert run["status"] == "COMPLETED"
    assert call(client, "GET", f"/api/v1/runs/{run['run_id']}", gina).status_code == 404
    assert run["run_id"] not in {
        r["run_id"] for r in call(client, "GET", "/api/v1/runs", gina).json()["runs"]
    }
    assert call(client, "GET", "/api/v1/runs/run_0000000000000000", alice).status_code == 404
    assert call(client, "GET", "/api/v1/runs", alice, params={"status": "BOGUS"}).status_code == 400


def test_every_documented_operation_was_exercised() -> None:
    # Runs last in this module (pytest preserves definition order).
    assert CONTRACT.operations() - CONTRACT.covered == set()
