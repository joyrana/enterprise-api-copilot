"""Run lifecycle service shared by the platform facade and the internal agent API.

* Runs are tenant-scoped: another tenant's run is indistinguishable from a missing one.
* Approving requires the caller to repeat the exact ``action_hash`` that was displayed,
  so a human can never approve something other than what they saw (ADR-0006).
* A per-run lock serialises approve/reject/resume; a second approval gets a conflict.
* ``RunView`` is the public projection: no internal results, no tokens, text redacted.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ai.agent.contracts import PendingApproval, RunEvent, RunState, RunStatus
from ai.agent.orchestrator import CheckpointStore, Orchestrator
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
from skills.runtime.redaction import redact, redact_text


class RunNotFoundError(LookupError):
    pass


class RunConflictError(RuntimeError):
    pass


class RunForbiddenError(PermissionError):
    pass


class TimelineEvent(BaseModel):
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class RunView(BaseModel):
    run_id: str
    status: RunStatus
    intent: str | None
    query: str
    environment: str
    message: str
    requested_by: str
    created_at: str
    elapsed_s: float
    evidence: list[str]
    missing_fields: list[str]
    tool_calls: int
    pending_approval: PendingApproval | None
    timeline: list[TimelineEvent]

    @classmethod
    def of(cls, state: RunState) -> RunView:
        return cls(
            run_id=state.run_id,
            status=state.status,
            intent=state.intent.intent.value if state.intent else None,
            query=redact_text(state.query),
            environment=state.environment,
            message=redact_text(state.message),
            requested_by=state.principal.subject,
            created_at=datetime.fromtimestamp(_created(state), UTC).isoformat(),
            elapsed_s=state.elapsed_s,
            evidence=state.evidence,
            missing_fields=state.missing_fields,
            tool_calls=state.tool_calls,
            pending_approval=state.pending_approval,
            timeline=[TimelineEvent(kind=e.kind, detail=redact(e.detail)) for e in state.events],
        )


def _created(state: RunState) -> float:
    for event in state.events:
        if event.kind == "created":
            return float(event.detail.get("at", state.started_at))
    return state.started_at


class RunService:
    def __init__(
        self,
        orchestrator: Orchestrator,
        store: CheckpointStore,
        approvals: ApprovalService | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.store = store
        self.approvals = approvals
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, run_id: str) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    async def start(self, principal: Principal, query: str, environment: str) -> RunState:
        state = await self.orchestrator.run(query, principal=principal, environment=environment)
        state.events.insert(0, RunEvent(kind="created", detail={"at": state.started_at}))
        self.store.save(state)
        return state

    def get(self, run_id: str, tenant_id: str) -> RunState:
        try:
            state = self.store.load(run_id)
        except ValueError as exc:
            raise RunNotFoundError(run_id) from exc
        if state is None or state.principal.tenant_id != tenant_id:
            raise RunNotFoundError(run_id)
        return state

    def list(
        self, tenant_id: str, *, status: RunStatus | None = None, limit: int = 20
    ) -> list[RunState]:
        return self.store.list_runs(tenant_id, status=status.value if status else None, limit=limit)

    async def approve(self, run_id: str, approver: Principal, action_hash: str) -> RunState:
        if self.approvals is None:
            raise RunForbiddenError("approvals are not handled by this service")
        async with self._lock(run_id):
            state = self.get(run_id, approver.tenant_id)
            pending = state.pending_approval
            if state.status is not RunStatus.AWAITING_APPROVAL or pending is None:
                raise RunConflictError("run is not awaiting approval")
            if pending.action_hash != action_hash:
                raise RunConflictError("action hash does not match the pending action")
            try:
                token = await self.approvals.approve(
                    approver=approver,
                    action_hash=action_hash,
                    tenant_id=approver.tenant_id,
                    environment=pending.environment,
                )
            except Exception as exc:  # SkillError (FORBIDDEN, INVALID_INPUT)
                raise RunForbiddenError(str(exc)) from exc
            resumed = await self.orchestrator.resume(run_id, approval_token=token)
            resumed.events.append(RunEvent(kind="approved", detail={"approver": approver.subject}))
            self.store.save(resumed)
            return resumed

    async def resume_with_token(self, run_id: str, tenant_id: str, approval_token: str) -> RunState:
        async with self._lock(run_id):
            state = self.get(run_id, tenant_id)
            if state.status is not RunStatus.AWAITING_APPROVAL:
                raise RunConflictError("run is not awaiting approval")
            resumed = await self.orchestrator.resume(run_id, approval_token=approval_token)
            self.store.save(resumed)
            return resumed

    async def reject(self, run_id: str, approver: Principal, reason: str | None) -> RunState:
        async with self._lock(run_id):
            state = self.get(run_id, approver.tenant_id)
            if state.status is not RunStatus.AWAITING_APPROVAL:
                raise RunConflictError("run is not awaiting approval")
            if self.approvals is not None:
                try:
                    await self.approvals.check_approver(approver, state.environment)
                except Exception as exc:
                    raise RunForbiddenError(str(exc)) from exc
            state.status = RunStatus.REJECTED
            state.message = "The pending action was rejected by an approver; nothing was executed."
            state.pending_approval = None
            state.events.append(
                RunEvent(
                    kind="rejected", detail={"approver": approver.subject, "reason": reason or ""}
                )
            )
            self.store.save(state)
            return state
