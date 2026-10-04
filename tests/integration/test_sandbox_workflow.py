"""End-to-end sandbox workflow (master prompt §11) through the real skill runtime.

import spec → search → explain auth/schema → validated request → policy + approval →
execute on the sandbox gateway → correlation id + cURL → idempotent replay.
"""

from __future__ import annotations

from typing import Any

import httpx

from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
from skills.runtime.errors import SkillErrorCode
from skills.runtime.policy import LocalPolicyEngine
from tests.support import FaultTransport, build_harness

APPROVER = Principal(subject="priya", tenant_id="acme", roles=frozenset({"approver"}))
BODY = {"amount": 50000, "currency": "INR", "customer_id": "cust_acm0001"}


async def test_full_sandbox_workflow() -> None:
    h = build_harness()
    rt = h.services.runtime

    found = await rt.invoke("api.search", {"query": "create a new payment for a customer"}, h.ctx())
    assert found.ok and found.output
    assert found.output["results"][0]["operation_id"] == "createPayment"
    assert found.output["results"][0]["invocation_skill"] == "api.call.write"

    described = await rt.invoke("api.describe", {"operation_id": "createPayment"}, h.ctx())
    assert described.ok and described.output
    assert described.output["required_scopes"] == ["payments:write"]
    assert described.output["requires_idempotency_key"] is True
    assert "OAuth 2.0 client credentials" in described.output["authentication"]

    invalid = await rt.invoke(
        "api.call.write",
        {
            "operation_id": "createPayment",
            "body": {"amount": 5, "currency": "INR", "customer_id": "cust_acm0001"},
        },
        h.ctx(idempotency_key="idem-bad"),
    )
    # Validated before approval: nobody is asked to approve a request that cannot succeed.
    assert invalid.error and invalid.error.code is SkillErrorCode.INVALID_INPUT
    assert invalid.action_hash is None

    args = {"operation_id": "createPayment", "body": BODY}
    pending = await rt.invoke("api.call.write", args, h.ctx(idempotency_key="idem-1"))
    assert pending.error and pending.error.code is SkillErrorCode.APPROVAL_REQUIRED
    assert len(h.app.state.sandbox.tenant("acme").payments) == 3  # nothing executed

    approvals = ApprovalService(h.services.approval_signer, LocalPolicyEngine())
    token = await approvals.approve(
        approver=APPROVER,
        action_hash=pending.error.details["action_hash"],
        tenant_id="acme",
        environment="sandbox",
    )
    done = await rt.invoke(
        "api.call.write", args, h.ctx(idempotency_key="idem-1", approval_token=token)
    )
    assert done.ok and done.output, done.error
    out: dict[str, Any] = done.output
    assert out["status_code"] == 201 and out["ok"]
    assert out["correlation_id"] == done.correlation_id
    assert out["response_body"]["status"] == "authorized"
    assert "$COPILOT_TOKEN" in out["curl"] and "Idempotency-Key: idem-1" in out["curl"]
    assert len(h.app.state.sandbox.tenant("acme").payments) == 4

    again = await rt.invoke(
        "api.call.write", args, h.ctx(idempotency_key="idem-1", approval_token=token)
    )
    assert again.ok and again.replayed
    assert len(h.app.state.sandbox.tenant("acme").payments) == 4

    audit_outcomes = [
        (e.skill_id, e.outcome) for e in h.audit.events if e.skill_id == "api.call.write"
    ]
    assert ("api.call.write", "succeeded") in audit_outcomes and (
        "api.call.write",
        "replayed",
    ) in audit_outcomes
    for event in h.audit.events:
        assert "Bearer" not in event.model_dump_json()


async def test_schema_validation_blocks_bad_request_before_upstream() -> None:
    h = build_harness()
    rt = h.services.runtime
    bad = {
        "operation_id": "createPayment",
        "body": {"amount": 5, "currency": "XXX", "customer_id": "nope"},
    }
    res = await rt.invoke("api.call.write", bad, h.ctx(idempotency_key="k-bad"))
    assert res.error and res.error.code is SkillErrorCode.INVALID_INPUT
    assert len(res.error.details["violations"]) >= 2
    assert len(h.app.state.sandbox.tenant("acme").payments) == 3


async def test_read_call_and_tenant_isolation() -> None:
    h = build_harness()
    acme = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listPayments", "query": {"limit": 10}}, h.ctx()
    )
    assert acme.ok and acme.output
    ids = {p["id"] for p in acme.output["response_body"]["data"]}
    assert ids and all(i.startswith("pay_acm") for i in ids)


async def test_scope_errors_are_reported_not_hidden() -> None:
    h = build_harness(client_id="acme-readonly-app")
    pending = await h.services.runtime.invoke(
        "api.call.write",
        {"operation_id": "createPayment", "body": BODY},
        h.ctx(idempotency_key="k1"),
    )
    approvals = ApprovalService(h.services.approval_signer, LocalPolicyEngine())
    token = await approvals.approve(
        approver=APPROVER,
        action_hash=pending.action_hash or "",
        tenant_id="acme",
        environment="sandbox",
    )
    res = await h.services.runtime.invoke(
        "api.call.write",
        {"operation_id": "createPayment", "body": BODY},
        h.ctx(idempotency_key="k1", approval_token=token),
    )
    # The read-only client cannot obtain a payments:write token: the token endpoint refuses.
    assert res.error and res.error.code is SkillErrorCode.UPSTREAM_ERROR
    assert res.error.details["status_code"] == 400


async def test_wrong_skill_for_method_rejected() -> None:
    h = build_harness()
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "createPayment", "body": BODY}, h.ctx()
    )
    assert res.error and res.error.code is SkillErrorCode.INVALID_INPUT
    assert "api.call.write" in res.error.message


async def test_viewer_cannot_execute() -> None:
    h = build_harness()
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listPayments"}, h.ctx(roles=frozenset({"viewer"}))
    )
    assert res.error and res.error.code is SkillErrorCode.FORBIDDEN


async def test_unconfigured_environment_rejected() -> None:
    h = build_harness()
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listPayments"}, h.ctx(env="production")
    )
    assert res.error and res.error.code is SkillErrorCode.ENVIRONMENT_NOT_ALLOWED


async def test_path_traversal_in_path_params_is_encoded() -> None:
    h = build_harness()
    res = await h.services.runtime.invoke(
        "api.call.read",
        {"operation_id": "getPayment", "path_params": {"payment_id": "../customers"}},
        h.ctx(),
    )
    assert res.error and res.error.code is SkillErrorCode.INVALID_INPUT  # fails the spec pattern


async def test_transient_503_is_retried_then_succeeds() -> None:
    h = build_harness()
    transport = FaultTransport(httpx.ASGITransport(app=h.app), "503", times=2)
    h.services.gateway._http._transport = transport  # inject faults at the transport layer
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listCustomers"}, h.ctx()
    )
    assert res.ok and res.attempts == 3 and transport.api_calls == 3


async def test_persistent_503_fails_with_retryable_error() -> None:
    h = build_harness()
    transport = FaultTransport(httpx.ASGITransport(app=h.app), "503", times=10)
    h.services.gateway._http._transport = transport
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listCustomers"}, h.ctx()
    )
    assert (
        res.error and res.error.code is SkillErrorCode.UPSTREAM_UNAVAILABLE and res.error.retryable
    )
    assert transport.api_calls == 3


async def test_rate_limit_surfaces_retry_after() -> None:
    h = build_harness()
    transport = FaultTransport(httpx.ASGITransport(app=h.app), "429", times=1)
    h.services.gateway._http._transport = transport
    res = await h.services.runtime.invoke(
        "api.call.read", {"operation_id": "listCustomers"}, h.ctx()
    )
    assert (
        res.ok
        and res.output
        and res.output["status_code"] == 429
        and res.output["retry_after_s"] == 30
    )
