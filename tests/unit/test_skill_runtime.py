"""Skill runtime enforcement: the security invariants of ADR-0006."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, Field

from ai.telemetry import SpanRecorder, Telemetry
from skills.runtime.approvals import ApprovalSigner, InMemoryApprovalStore
from skills.runtime.audit import InMemoryAuditSink
from skills.runtime.contracts import (
    InvocationContext,
    Principal,
    RetryPolicy,
    SideEffect,
    SkillDefinition,
)
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.idempotency import InMemoryIdempotencyStore
from skills.runtime.policy import EnvironmentPolicy, LocalPolicyEngine
from skills.runtime.registry import SkillRegistry
from skills.runtime.runtime import SkillRuntime

KEY = b"k" * 32


class EchoIn(BaseModel):
    text: str = Field(max_length=50)


class EchoOut(BaseModel):
    text: str


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


async def _no_sleep(_: float) -> None:
    return None


def build(
    *, extra: list[SkillDefinition[Any, Any]] | None = None, clock: Clock | None = None
) -> tuple[SkillRuntime, dict[str, Any]]:
    clock = clock or Clock()
    calls: dict[str, Any] = {"write": 0, "flaky": 0}

    async def echo(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        return EchoOut(text=inp.text)

    async def write(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        calls["write"] += 1
        return EchoOut(text=f"wrote {inp.text}")

    async def flaky(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        calls["flaky"] += 1
        if calls["flaky"] < 3:
            raise SkillError(SkillErrorCode.UPSTREAM_UNAVAILABLE, "down")
        return EchoOut(text="ok")

    async def slow(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        await asyncio.sleep(1)
        return EchoOut(text="late")

    async def bad_output(inp: EchoIn, ctx: InvocationContext) -> dict[str, Any]:
        return {"unexpected": True}

    async def crash(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        raise RuntimeError("secret internal detail sk-live-abcdefghijklmnopqrstuv")

    reg = SkillRegistry()
    common = {
        "input_model": EchoIn,
        "output_model": EchoOut,
        "version": "1.0.0",
        "description": "t",
    }
    reg.register(
        SkillDefinition(
            id="t.echo",
            name="echo",
            handler=echo,
            required_permissions=frozenset({"catalog:read"}),
            side_effect=SideEffect.NONE,
            **common,
        )
    )
    reg.register(
        SkillDefinition(
            id="t.write",
            name="write",
            handler=write,
            required_permissions=frozenset({"api:invoke:write"}),
            side_effect=SideEffect.WRITE,
            idempotency_required=True,
            **common,
        )
    )
    reg.register(
        SkillDefinition(
            id="t.delete",
            name="delete",
            handler=write,
            required_permissions=frozenset({"api:invoke:delete"}),
            side_effect=SideEffect.DESTRUCTIVE,
            idempotency_required=True,
            **common,
        )
    )
    reg.register(
        SkillDefinition(
            id="t.flaky",
            name="flaky",
            handler=flaky,
            required_permissions=frozenset({"catalog:read"}),
            side_effect=SideEffect.READ,
            retry=RetryPolicy(max_attempts=3),
            **common,
        )
    )
    reg.register(
        SkillDefinition(
            id="t.slow",
            name="slow",
            handler=slow,
            required_permissions=frozenset({"catalog:read"}),
            side_effect=SideEffect.READ,
            timeout_s=0.05,
            **common,
        )
    )
    reg.register(
        SkillDefinition(
            id="t.bad",
            name="bad",
            handler=bad_output,
            required_permissions=frozenset({"catalog:read"}),
            side_effect=SideEffect.NONE,
            **common,
        )
    )  # type: ignore[arg-type]
    reg.register(
        SkillDefinition(
            id="t.crash",
            name="crash",
            handler=crash,
            required_permissions=frozenset({"catalog:read"}),
            side_effect=SideEffect.NONE,
            **common,
        )
    )
    for skill in extra or []:
        reg.register(skill)

    audit = InMemoryAuditSink()
    recorder = SpanRecorder()
    runtime = SkillRuntime(
        registry=reg,
        policy=LocalPolicyEngine(),
        environments=EnvironmentPolicy(
            allowed=frozenset({"sandbox", "production"}), write_enabled=frozenset({"sandbox"})
        ),
        approval_signer=ApprovalSigner(KEY, clock=clock),
        approval_store=InMemoryApprovalStore(clock=clock),
        idempotency_store=InMemoryIdempotencyStore(),
        audit_sink=audit,
        telemetry=Telemetry(recorder),
        sleep=_no_sleep,
    )
    return runtime, {
        "calls": calls,
        "audit": audit,
        "recorder": recorder,
        "clock": clock,
        "signer": ApprovalSigner(KEY, clock=clock),
    }


DEV = Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"}))
ADMIN = Principal(subject="root", tenant_id="acme", roles=frozenset({"admin"}))
VIEWER = Principal(subject="vic", tenant_id="acme", roles=frozenset({"viewer"}))


def ctx(principal: Principal = DEV, env: str = "sandbox", **kw: Any) -> InvocationContext:
    return InvocationContext(principal=principal, environment=env, correlation_id="c-1", **kw)


async def test_happy_path_and_audit() -> None:
    rt, h = build()
    res = await rt.invoke("t.echo", {"text": "hi"}, ctx())
    assert res.ok and res.output == {"text": "hi"} and res.attempts == 1
    assert h["audit"].events[-1].outcome == "succeeded"
    span = h["recorder"].named("skill.invoke")[-1]
    assert span.attributes["gen_ai.tool.name"] == "t.echo"


async def test_unknown_skill() -> None:
    rt, _ = build()
    res = await rt.invoke("nope", {}, ctx())
    assert not res.ok and res.error and res.error.code is SkillErrorCode.UNKNOWN_SKILL


async def test_invalid_input_does_not_echo_values() -> None:
    rt, _ = build()
    res = await rt.invoke("t.echo", {"text": "x" * 51 + "sk-live-abcdefghijklmnopqrstuv"}, ctx())
    assert res.error and res.error.code is SkillErrorCode.INVALID_INPUT
    assert "sk-live" not in res.model_dump_json()


async def test_unknown_environment_rejected_before_policy() -> None:
    rt, _ = build()
    res = await rt.invoke("t.echo", {"text": "hi"}, ctx(env="staging"))
    assert res.error and res.error.code is SkillErrorCode.ENVIRONMENT_NOT_ALLOWED


async def test_production_writes_disabled_by_default() -> None:
    rt, h = build()
    res = await rt.invoke("t.write", {"text": "x"}, ctx(env="production", idempotency_key="k1"))
    assert res.error and res.error.code is SkillErrorCode.ENVIRONMENT_NOT_ALLOWED
    assert h["calls"]["write"] == 0


async def test_missing_permission_forbidden() -> None:
    rt, h = build()
    res = await rt.invoke("t.write", {"text": "x"}, ctx(VIEWER, idempotency_key="k1"))
    assert res.error and res.error.code is SkillErrorCode.FORBIDDEN
    assert res.error.details["missing_permissions"] == ["api:invoke:write"]
    assert h["audit"].events[-1].outcome == "denied"


async def test_write_requires_idempotency_key_then_approval() -> None:
    rt, h = build()
    res = await rt.invoke("t.write", {"text": "x"}, ctx())
    assert res.error and res.error.code is SkillErrorCode.IDEMPOTENCY_KEY_REQUIRED
    res = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_REQUIRED
    assert res.error.details["action_hash"] == res.action_hash
    assert h["calls"]["write"] == 0


async def test_approved_write_executes_once_and_replays() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme")
    ok = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token))
    assert ok.ok and h["calls"]["write"] == 1
    assert h["audit"].events[-1].approver == "bob"
    again = await rt.invoke(
        "t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token)
    )
    assert again.ok and again.replayed and h["calls"]["write"] == 1


async def test_approval_bound_to_exact_arguments() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme")
    res = await rt.invoke(
        "t.write", {"text": "CHANGED"}, ctx(idempotency_key="k2", approval_token=token)
    )
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID
    assert h["calls"]["write"] == 0


async def test_approval_bound_to_environment_and_subject() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme")
    other = Principal(subject="mallory", tenant_id="acme", roles=frozenset({"developer"}))
    res = await rt.invoke(
        "t.write", {"text": "x"}, ctx(other, idempotency_key="k9", approval_token=token)
    )
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID
    assert h["calls"]["write"] == 0


async def test_approval_single_use_across_idempotency_keys() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme")
    assert (
        await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token))
    ).ok
    res = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k2", approval_token=token))
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID
    assert h["calls"]["write"] == 1


async def test_expired_and_forged_approvals_rejected() -> None:
    clock = Clock()
    rt, h = build(clock=clock)
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme", ttl_s=60)
    clock.now += 61
    res = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token))
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID
    forged = ApprovalSigner(b"z" * 32, clock=clock).issue(
        action=first.action_hash, approver="bob", tenant_id="acme"
    )
    res = await rt.invoke(
        "t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=forged)
    )
    assert res.error and res.error.message == "approval token signature mismatch"
    assert h["calls"]["write"] == 0


async def test_cross_tenant_approval_rejected() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="globex")
    res = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token))
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID


async def test_idempotency_conflict() -> None:
    rt, h = build()
    first = await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1"))
    token = h["signer"].issue(action=first.action_hash, approver="bob", tenant_id="acme")
    assert (
        await rt.invoke("t.write", {"text": "x"}, ctx(idempotency_key="k1", approval_token=token))
    ).ok
    res = await rt.invoke("t.write", {"text": "y"}, ctx(idempotency_key="k1"))
    assert res.error and res.error.code is SkillErrorCode.IDEMPOTENCY_CONFLICT


async def test_destructive_requires_distinct_approver() -> None:
    rt, h = build()
    first = await rt.invoke("t.delete", {"text": "x"}, ctx(ADMIN, idempotency_key="d1"))
    self_token = h["signer"].issue(action=first.action_hash, approver="root", tenant_id="acme")
    res = await rt.invoke(
        "t.delete", {"text": "x"}, ctx(ADMIN, idempotency_key="d1", approval_token=self_token)
    )
    assert res.error and res.error.code is SkillErrorCode.APPROVAL_INVALID
    other = h["signer"].issue(action=first.action_hash, approver="carol", tenant_id="acme")
    assert (
        await rt.invoke(
            "t.delete", {"text": "x"}, ctx(ADMIN, idempotency_key="d1", approval_token=other)
        )
    ).ok


async def test_retry_only_retryable_errors() -> None:
    rt, _h = build()
    res = await rt.invoke("t.flaky", {"text": "x"}, ctx())
    assert res.ok and res.attempts == 3


async def test_timeout() -> None:
    rt, _ = build()
    res = await rt.invoke("t.slow", {"text": "x"}, ctx())
    assert res.error and res.error.code is SkillErrorCode.TIMEOUT and res.error.retryable


async def test_output_contract_enforced() -> None:
    rt, _ = build()
    res = await rt.invoke("t.bad", {"text": "x"}, ctx())
    assert res.error and res.error.code is SkillErrorCode.INVALID_OUTPUT


async def test_internal_errors_do_not_leak() -> None:
    rt, _h = build()
    res = await rt.invoke("t.crash", {"text": "x"}, ctx())
    assert res.error and res.error.code is SkillErrorCode.INTERNAL_ERROR
    assert "secret" not in res.model_dump_json()


async def test_audit_redacts_secrets() -> None:
    rt, h = build()
    await rt.invoke("t.echo", {"text": "Bearer abcdefghijklmnop"}, ctx())
    assert h["audit"].events[-1].arguments == {"text": "[REDACTED]"}


def test_side_effect_skill_must_require_idempotency() -> None:
    async def handler(inp: EchoIn, ctx: InvocationContext) -> EchoOut:
        return EchoOut(text="")

    with pytest.raises(ValueError, match="idempotency"):
        SkillDefinition(
            id="x",
            name="x",
            version="1",
            description="",
            input_model=EchoIn,
            output_model=EchoOut,
            handler=handler,
            required_permissions=frozenset({"a"}),
            side_effect=SideEffect.WRITE,
        )
