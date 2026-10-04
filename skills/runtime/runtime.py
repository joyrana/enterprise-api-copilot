"""The skill runtime: the only path from a proposed tool call to its execution.

Order of checks (ADR-0006): resolve → validate input → environment allowlist → policy →
approval (side-effecting skills) → idempotency → execute with timeout/retries →
validate output → audit + telemetry.

``invoke`` never raises for skill-level failures; it returns a ``SkillResult`` with a
typed error so callers (agent, MCP adapter) handle every outcome explicitly.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from ai.telemetry import Telemetry
from skills.runtime.approvals import ApprovalSigner, ApprovalStore, action_hash
from skills.runtime.audit import AuditEvent, AuditSink
from skills.runtime.contracts import (
    InvocationContext,
    SideEffect,
    SkillDefinition,
    SkillErrorInfo,
    SkillResult,
)
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.idempotency import IdempotencyRecord, IdempotencyStore
from skills.runtime.policy import EnvironmentPolicy, PolicyDecisionPort
from skills.runtime.registry import SkillRegistry

_log = logging.getLogger(__name__)

Sleeper = Callable[[float], Awaitable[None]]


def _validation_summary(exc: ValidationError) -> list[dict[str, Any]]:
    # Location and type only: never echo the offending input value back.
    return [{"loc": [str(p) for p in err["loc"]], "type": err["type"]} for err in exc.errors()]


class SkillRuntime:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        policy: PolicyDecisionPort,
        environments: EnvironmentPolicy,
        approval_signer: ApprovalSigner,
        approval_store: ApprovalStore,
        idempotency_store: IdempotencyStore,
        audit_sink: AuditSink,
        telemetry: Telemetry | None = None,
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self.registry = registry
        self._policy = policy
        self._environments = environments
        self._signer = approval_signer
        self._approvals = approval_store
        self._idempotency = idempotency_store
        self._audit = audit_sink
        self._telemetry = telemetry or Telemetry()
        self._sleep = sleep

    def compute_action_hash(
        self, skill_id: str, arguments: dict[str, Any], ctx: InvocationContext
    ) -> str:
        skill = self.registry.get(skill_id)
        if skill is None:
            raise SkillError(SkillErrorCode.UNKNOWN_SKILL, f"unknown skill '{skill_id}'")
        validated = skill.input_model.model_validate(arguments)
        return action_hash(
            skill_id=skill.id,
            skill_version=skill.version,
            arguments=validated.model_dump(mode="json"),
            environment=ctx.environment,
            tenant_id=ctx.principal.tenant_id,
            subject=ctx.principal.subject,
        )

    async def invoke(
        self, skill_id: str, arguments: dict[str, Any], ctx: InvocationContext
    ) -> SkillResult:
        started = time.perf_counter()
        skill = self.registry.get(skill_id)
        with self._telemetry.span(
            "skill.invoke",
            **{
                "gen_ai.tool.name": skill_id,
                "copilot.environment": ctx.environment,
                "copilot.tenant_id": ctx.principal.tenant_id,
            },
        ) as span:
            if skill is None:
                result = self._failure(
                    skill_id,
                    "?",
                    ctx,
                    SkillError(SkillErrorCode.UNKNOWN_SKILL, f"unknown skill '{skill_id}'"),
                    started,
                )
                span.set("copilot.outcome", "failed")
                span.set("error.type", result.error.code if result.error else "")
                return result
            result, audit_fields = await self._invoke_known(skill, arguments, ctx, started)
            span.set("copilot.outcome", audit_fields["outcome"])
            span.set("copilot.attempts", result.attempts)
            if result.error:
                span.set("error.type", result.error.code.value)
        if skill.audit_required or audit_fields["outcome"] != "succeeded":
            await self._audit.emit(
                AuditEvent.build(
                    arguments=arguments,
                    skill_id=skill.id,
                    skill_version=skill.version,
                    side_effect=skill.side_effect.value,
                    tenant_id=ctx.principal.tenant_id,
                    subject=ctx.principal.subject,
                    environment=ctx.environment,
                    correlation_id=ctx.correlation_id,
                    run_id=ctx.run_id,
                    error_code=result.error.code.value if result.error else None,
                    action_hash=result.action_hash,
                    attempts=result.attempts,
                    duration_ms=result.duration_ms,
                    **audit_fields,
                )
            )
        return result

    async def _invoke_known(
        self,
        skill: SkillDefinition[Any, Any],
        arguments: dict[str, Any],
        ctx: InvocationContext,
        started: float,
    ) -> tuple[SkillResult, dict[str, Any]]:
        denied: dict[str, Any] = {"outcome": "denied"}
        # 1. input validation
        try:
            validated: BaseModel = skill.input_model.model_validate(arguments)
        except ValidationError as exc:
            err = SkillError(
                SkillErrorCode.INVALID_INPUT,
                "input does not match the skill schema",
                details={"errors": _validation_summary(exc)},
            )
            return self._failure(skill.id, skill.version, ctx, err, started), {"outcome": "failed"}

        # 2. environment allowlist (before policy, so unknown environments never reach a PDP)
        if not self._environments.is_allowed(ctx.environment):
            err = SkillError(
                SkillErrorCode.ENVIRONMENT_NOT_ALLOWED,
                f"environment '{ctx.environment}' is not enabled",
            )
            return self._failure(skill.id, skill.version, ctx, err, started), denied
        if skill.side_effect.requires_approval and not self._environments.writes_enabled(
            ctx.environment
        ):
            err = SkillError(
                SkillErrorCode.ENVIRONMENT_NOT_ALLOWED,
                f"writes are disabled in environment '{ctx.environment}'",
            )
            return self._failure(skill.id, skill.version, ctx, err, started), denied

        # 3. policy decision (server-side, independent of any model output)
        decision = await self._policy.decide(
            ctx.principal, skill.required_permissions, ctx.environment
        )
        if not decision.allowed:
            err = SkillError(
                SkillErrorCode.FORBIDDEN,
                "not authorized for this skill",
                details={"missing_permissions": sorted(decision.missing_permissions)},
            )
            return self._failure(skill.id, skill.version, ctx, err, started), denied

        # 3b. preflight: validate against external contracts (e.g. the API schema) before any
        # approval is requested.
        if skill.preflight is not None:
            try:
                await asyncio.wait_for(skill.preflight(validated, ctx), timeout=skill.timeout_s)
            except SkillError as preflight_error:
                return self._failure(skill.id, skill.version, ctx, preflight_error, started), {
                    "outcome": "failed"
                }
            except TimeoutError:
                err = SkillError(SkillErrorCode.TIMEOUT, "preflight validation timed out")
                return self._failure(skill.id, skill.version, ctx, err, started), {
                    "outcome": "failed"
                }
            except Exception as exc:
                _log.exception(
                    "unexpected preflight failure in %s (%s)", skill.id, type(exc).__name__
                )
                err = SkillError(SkillErrorCode.INTERNAL_ERROR, "internal error in skill")
                return self._failure(skill.id, skill.version, ctx, err, started), {
                    "outcome": "failed"
                }

        canonical_args = validated.model_dump(mode="json")
        act = action_hash(
            skill_id=skill.id,
            skill_version=skill.version,
            arguments=canonical_args,
            environment=ctx.environment,
            tenant_id=ctx.principal.tenant_id,
            subject=ctx.principal.subject,
        )
        audit: dict[str, Any] = {}

        # 4. approval and idempotency for side-effecting skills
        if skill.side_effect.requires_approval:
            if not ctx.idempotency_key:
                err = SkillError(
                    SkillErrorCode.IDEMPOTENCY_KEY_REQUIRED,
                    "side-effecting skills require an idempotency key",
                )
                return self._failure(skill.id, skill.version, ctx, err, started, act), denied
            async with self._idempotency.lock(ctx.principal.tenant_id, ctx.idempotency_key):
                existing = await self._idempotency.get(ctx.principal.tenant_id, ctx.idempotency_key)
                if existing is not None:
                    if existing.action_hash != act:
                        err = SkillError(
                            SkillErrorCode.IDEMPOTENCY_CONFLICT,
                            "idempotency key was already used for a different action",
                        )
                        return (
                            self._failure(skill.id, skill.version, ctx, err, started, act),
                            denied,
                        )
                    replay = existing.result.model_copy(update={"replayed": True})
                    return replay, {"outcome": "replayed"}

                if not ctx.approval_token:
                    err = SkillError(
                        SkillErrorCode.APPROVAL_REQUIRED,
                        "this action needs an approval bound to its exact arguments",
                        details={"action_hash": act, "side_effect": skill.side_effect.value},
                    )
                    return (
                        self._failure(skill.id, skill.version, ctx, err, started, act),
                        {"outcome": "denied"},
                    )
                try:
                    grant = self._signer.verify(
                        ctx.approval_token, expected_action=act, tenant_id=ctx.principal.tenant_id
                    )
                except SkillError as approval_error:
                    return self._failure(
                        skill.id, skill.version, ctx, approval_error, started, act
                    ), denied
                if (
                    skill.side_effect is SideEffect.DESTRUCTIVE
                    and grant.approver == ctx.principal.subject
                ):
                    err = SkillError(
                        SkillErrorCode.APPROVAL_INVALID,
                        "destructive actions need an approver other than the requester",
                    )
                    return self._failure(skill.id, skill.version, ctx, err, started, act), denied
                if not await self._approvals.consume(grant.approval_id, grant.expires_at):
                    err = SkillError(SkillErrorCode.APPROVAL_INVALID, "approval was already used")
                    return self._failure(skill.id, skill.version, ctx, err, started, act), denied
                audit = {"approval_id": grant.approval_id, "approver": grant.approver}

                result = await self._execute(skill, validated, ctx, started, act)
                # Only definitive outcomes are cached; retryable failures may be retried
                # with the same key (and a fresh approval).
                if result.ok or (result.error and not result.error.retryable):
                    await self._idempotency.put(
                        ctx.principal.tenant_id, ctx.idempotency_key, IdempotencyRecord(act, result)
                    )
                return result, {"outcome": "succeeded" if result.ok else "failed", **audit}

        result = await self._execute(skill, validated, ctx, started, act)
        return result, {"outcome": "succeeded" if result.ok else "failed"}

    async def _execute(
        self,
        skill: SkillDefinition[Any, Any],
        validated: BaseModel,
        ctx: InvocationContext,
        started: float,
        act: str,
    ) -> SkillResult:
        attempt = 0
        while True:
            attempt += 1
            try:
                raw = await asyncio.wait_for(skill.handler(validated, ctx), timeout=skill.timeout_s)
            except TimeoutError:
                error = SkillError(SkillErrorCode.TIMEOUT, f"skill exceeded {skill.timeout_s}s")
            except SkillError as exc:
                error = exc
            except Exception as exc:
                _log.exception("unexpected failure in skill %s (%s)", skill.id, type(exc).__name__)
                error = SkillError(SkillErrorCode.INTERNAL_ERROR, "internal error in skill")
            else:
                try:
                    output = skill.output_model.model_validate(
                        raw.model_dump() if isinstance(raw, BaseModel) else raw
                    )
                except ValidationError as exc:
                    err = SkillError(
                        SkillErrorCode.INVALID_OUTPUT,
                        "skill produced output that violates its contract",
                        details={"errors": _validation_summary(exc)},
                    )
                    return self._failure(skill.id, skill.version, ctx, err, started, act, attempt)
                return SkillResult(
                    skill_id=skill.id,
                    skill_version=skill.version,
                    ok=True,
                    output=output.model_dump(mode="json"),
                    attempts=attempt,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    correlation_id=ctx.correlation_id,
                    action_hash=act,
                )
            if not error.retryable or attempt >= skill.retry.max_attempts:
                return self._failure(skill.id, skill.version, ctx, error, started, act, attempt)
            await self._sleep(skill.retry.backoff(attempt))

    @staticmethod
    def _failure(
        skill_id: str,
        version: str,
        ctx: InvocationContext,
        error: SkillError,
        started: float,
        act: str | None = None,
        attempts: int = 0,
    ) -> SkillResult:
        return SkillResult(
            skill_id=skill_id,
            skill_version=version,
            ok=False,
            error=SkillErrorInfo(
                code=error.code,
                message=error.message,
                retryable=error.retryable,
                details=error.details,
            ),
            attempts=attempts,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            correlation_id=ctx.correlation_id,
            action_hash=act,
        )
