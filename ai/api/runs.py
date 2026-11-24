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

from ai.agent.contracts import (
    ModelUsageTotals,
    PendingApproval,
    RunEvent,
    RunState,
    RunStatus,
    UIComponent,
)
from ai.agent.conversations import (
    Conversation,
    ConversationStore,
    InMemoryConversationStore,
    build_context,
)
from ai.agent.orchestrator import CheckpointStore, Orchestrator
from ai.storage.sql_store import SqlRuntimeStore
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
from skills.runtime.redaction import redact, redact_text


class RunNotFoundError(LookupError):
    pass


class ConversationNotFoundError(RunNotFoundError):
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
    mode: str = "deterministic"
    ui: list[UIComponent] = Field(default_factory=list)
    model: ModelUsageTotals | None = None
    conversation_id: str | None = None

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
            mode=state.mode,
            ui=[c.model_copy(update={"props": redact(c.props)}) for c in state.ui],
            model=state.model_usage,
            conversation_id=state.conversation_id,
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
        conversations: ConversationStore | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.store = store
        self.approvals = approvals
        # The SQL store doubles as the conversation store; otherwise keep them in memory.
        self.conversations: ConversationStore = conversations or (
            store if isinstance(store, SqlRuntimeStore) else InMemoryConversationStore()
        )
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, run_id: str) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    def create_conversation(self, principal: Principal) -> Conversation:
        return self.conversations.create_conversation(principal.tenant_id, principal.subject)

    def get_conversation(self, conversation_id: str, tenant_id: str) -> Conversation:
        """Another tenant's conversation is indistinguishable from a missing one."""
        conversation = self.conversations.get_conversation(conversation_id, tenant_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    def conversation_runs(self, conversation: Conversation) -> list[RunState]:
        states = []
        for run_id in conversation.run_ids:
            state = self.store.load(run_id)
            if state is not None and state.principal.tenant_id == conversation.tenant_id:
                states.append(state)
        return states

    async def start(
        self,
        principal: Principal,
        query: str,
        environment: str,
        conversation_id: str | None = None,
    ) -> RunState:
        context = None
        if conversation_id is not None:
            conversation = self.get_conversation(conversation_id, principal.tenant_id)
            previous = self.conversation_runs(conversation)
            if previous and self.orchestrator.awaiting_clarification(previous[-1]):
                # A plain next message while a run waits for an answer is that answer.
                return await self.clarify(previous[-1].run_id, principal, query)
            context = build_context(previous)
        state = await self.orchestrator.run(
            query,
            principal=principal,
            environment=environment,
            conversation_id=conversation_id,
            context=context,
        )
        state.events.insert(0, RunEvent(kind="created", detail={"at": state.started_at}))
        self.store.save(state)
        if conversation_id is not None:
            self.conversations.add_conversation_run(
                conversation_id, state.run_id, principal.tenant_id
            )
        return state

    async def clarify(self, run_id: str, principal: Principal, message: str) -> RunState:
        async with self._lock(run_id):
            state = self.get(run_id, principal.tenant_id)
            if not self.orchestrator.awaiting_clarification(state):
                raise RunConflictError("run is not waiting for a clarification")
            resumed = await self.orchestrator.clarify(run_id, message)
            self.store.save(resumed)
            return resumed

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
