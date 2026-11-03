"""Bounded orchestrator: classify → resolve skills → plan/execute → respond with UI.

Two modes, recorded on the run as ``RunState.mode``:

* **agentic** (a model is configured — Qwen3 4B on a local mlx-lm server by default): the LLM
  decides the intent and extracts entities (grounded against the request), the intent
  resolver fixes the skills that intent may use, an LLM step planner runs a bounded
  ReAct loop over those skills, and an LLM responder writes the answer and chooses UI
  components from the component registry. Every model decision is validated before it
  reaches the skill runtime. If the model is unreachable or returns invalid output, the
  run FAILS with that reason — it never falls back to rules or templates.
* **deterministic** (only when no model is configured, ``COPILOT_LLM_PROVIDER=none``):
  rules → template plan → template response.

Properties (tested in ``tests/unit/test_agent.py``):

* every tool call goes through ``SkillRuntime.invoke``; budgets cap steps, tool calls and
  wall-clock time;
* the environment comes from the caller and is never changed by request text;
* a side-effecting step without approval stops the run in ``AWAITING_APPROVAL`` with the
  exact action hash; ``resume`` continues from the checkpoint with an approval token and
  the *same* idempotency key;
* missing required arguments stop the run in ``NEEDS_CLARIFICATION`` instead of guessing;
* upstream 4xx outcomes trigger one bounded documentation lookup to explain the failure;
* in agentic mode the model can only call resolved skills, must describe an operation
  before calling it, must use its invocation skill, and cannot supply argument values the
  user did not (``ai.agent.grounding``).

This is the framework-independent core. A LangGraph adapter (Phase 4) maps each phase to
a node and uses a Postgres checkpointer; the state model below is already serialisable.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from ai.agent.binding import bind_call_arguments
from ai.agent.contracts import (
    Intent,
    ModelUsageTotals,
    PendingApproval,
    Plan,
    PlanStep,
    RunBudget,
    RunEvent,
    RunState,
    RunStatus,
)
from ai.agent.grounding import ground_call_arguments
from ai.agent.intent import IntentClassifier, RuleBasedIntentClassifier
from ai.agent.intent_llm import LLMIntentClassifier
from ai.agent.planner import BIND_SKILL, CALL_SKILLS, Planner, TemplatePlanner
from ai.agent.planner_llm import JWT_PLACEHOLDER, LLMStepPlanner, StepDecision
from ai.agent.resolver import IntentResolver
from ai.agent.responder import LLMResponder
from ai.agent.ui import build_components
from ai.models.base import (
    ModelProvider,
    ModelUnavailableError,
    ModelUsage,
    StructuredOutputError,
)
from ai.telemetry import Telemetry
from skills.runtime.contracts import InvocationContext, Principal, SkillResult
from skills.runtime.errors import SkillErrorCode
from skills.runtime.redaction import redact
from skills.runtime.runtime import SkillRuntime

_UPSTREAM_HINTS = {
    401: "401 unauthorized token missing expired",
    403: "403 forbidden token lacks scope",
    409: "409 conflict idempotency key reused",
    422: "422 validation error request body",
    429: "429 too many requests rate limit retry-after",
}
# Errors a model can fix by choosing different arguments: fed back as observations in
# agentic mode instead of ending the run.
_RECOVERABLE_CODES = {SkillErrorCode.INVALID_INPUT, SkillErrorCode.NOT_FOUND}
_STEP_NAMES = {
    "api.search": "search",
    "api.describe": "describe",
    "api.call.read": "call",
    "api.call.write": "call",
    "api.call.delete": "call",
    "code.generate": "codegen",
    "docs.search": "docs",
    "token.inspect": "inspect",
}
_MODEL_ERRORS = (StructuredOutputError, ModelUnavailableError)
_STAGE_NAMES = {
    "intent": "understanding the request",
    "plan": "planning the next step",
    "respond": "writing the reply",
}
_DENIAL_CODES = {
    SkillErrorCode.FORBIDDEN,
    SkillErrorCode.ENVIRONMENT_NOT_ALLOWED,
    SkillErrorCode.APPROVAL_INVALID,
    SkillErrorCode.IDEMPOTENCY_CONFLICT,
}


class CheckpointStore(Protocol):
    def save(self, state: RunState) -> None: ...

    def load(self, run_id: str) -> RunState | None: ...

    def list_runs(
        self, tenant_id: str, *, status: str | None = None, limit: int = 1000
    ) -> list[RunState]:
        """Runs of one tenant, newest first."""
        ...


def _run_created(state: RunState) -> float:
    for event in state.events:
        if event.kind == "created":
            return float(event.detail.get("at", state.started_at))
    return state.started_at


def _filter_runs(
    states: list[RunState], tenant_id: str, status: str | None, limit: int
) -> list[RunState]:
    out = [
        s
        for s in states
        if s.principal.tenant_id == tenant_id and (status is None or s.status.value == status)
    ]
    out.sort(key=_run_created, reverse=True)
    return out[:limit]


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._states: dict[str, str] = {}

    def save(self, state: RunState) -> None:
        self._states[state.run_id] = state.model_dump_json()

    def load(self, run_id: str) -> RunState | None:
        raw = self._states.get(run_id)
        return RunState.model_validate_json(raw) if raw else None

    def list_runs(
        self, tenant_id: str, *, status: str | None = None, limit: int = 1000
    ) -> list[RunState]:
        states = [RunState.model_validate_json(raw) for raw in self._states.values()]
        return _filter_runs(states, tenant_id, status, limit)


class FileCheckpointStore:
    """Durable local checkpoints (one JSON file per run). Postgres replaces this in Phase 4."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not run_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid run id")
        return self.root / f"{run_id}.json"

    def save(self, state: RunState) -> None:
        tmp = self._path(state.run_id).with_suffix(".tmp")
        tmp.write_text(state.model_dump_json(), encoding="utf-8")
        tmp.replace(self._path(state.run_id))

    def load(self, run_id: str) -> RunState | None:
        path = self._path(run_id)
        return (
            RunState.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    def list_runs(
        self, tenant_id: str, *, status: str | None = None, limit: int = 1000
    ) -> list[RunState]:
        """Linear scan — tests/demos only; use the SQL store for anything larger."""
        states = [
            RunState.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self.root.glob("run_*.json")
        ]
        return _filter_runs(states, tenant_id, status, limit)


class RunHaltError(Exception):
    def __init__(self, status: RunStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _lookup(value: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(path)
    return value


class Orchestrator:
    def __init__(
        self,
        runtime: SkillRuntime,
        *,
        llm: ModelProvider | None = None,
        classifier: IntentClassifier | None = None,
        planner: Planner | None = None,
        resolver: IntentResolver | None = None,
        checkpoints: CheckpointStore | None = None,
        budget: RunBudget | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.runtime = runtime
        self.llm = llm
        self.classifier: IntentClassifier = classifier or (
            LLMIntentClassifier(llm) if llm is not None else RuleBasedIntentClassifier()
        )
        self.planner = planner or TemplatePlanner()
        self.resolver = resolver or IntentResolver(runtime.registry)
        self.step_planner = LLMStepPlanner(llm) if llm is not None else None
        self.responder = LLMResponder(llm) if llm is not None else None
        self.checkpoints = checkpoints or InMemoryCheckpointStore()
        # Local models need more wall-clock time than the deterministic path.
        self.budget = budget or (RunBudget(deadline_s=240) if llm is not None else RunBudget())
        self.telemetry = telemetry or Telemetry()

    async def run(self, query: str, *, principal: Principal, environment: str) -> RunState:
        state = RunState(
            run_id=f"run_{uuid.uuid4().hex[:16]}",
            query=query,
            principal=principal,
            environment=environment,
            budget=self.budget,
            started_at=time.time(),
        )
        if self.llm is not None:
            state.model_usage = ModelUsageTotals(provider=self.llm.name, model=self.llm.model)
        with self.telemetry.span("agent.run", **{"copilot.run_id": state.run_id}) as span:
            agentic = self.step_planner is not None
            state.mode = "agentic" if agentic else "deterministic"
            try:
                state.intent = await self.classifier.aclassify(query)
            except _MODEL_ERRORS as exc:
                try:
                    self._model_failed(state, "intent", exc)
                except RunHaltError as failure:
                    self._finish(state, failure.status, failure.message)
                await self._respond(state)
                self.checkpoints.save(state)
                span.set("copilot.mode", state.mode)
                span.set("copilot.status", state.status.value)
                return state
            self._account_classifier(state)
            state.events.append(
                RunEvent(
                    kind="intent",
                    detail={
                        "intent": state.intent.intent.value,
                        "confidence": state.intent.confidence,
                        "rationale": state.intent.rationale,
                        "classifier": state.intent.classifier,
                    },
                )
            )
            span.set("copilot.intent", state.intent.intent.value)
            mentioned = state.intent.entities.environment
            if mentioned and mentioned != environment:
                state.events.append(
                    RunEvent(
                        kind="environment_mention_ignored",
                        detail={"mentioned": mentioned, "using": environment},
                    )
                )
            if state.intent.intent is Intent.UNSUPPORTED:
                self._finish(
                    state,
                    RunStatus.REJECTED,
                    "I can't help with that request. " + state.intent.rationale.rstrip(".") + ".",
                )
            elif state.intent.intent is Intent.CLARIFICATION_NEEDED:
                self._finish(
                    state,
                    RunStatus.NEEDS_CLARIFICATION,
                    "Could you say more about what you want to do — for example which API, "
                    "resource or error?",
                )
            elif agentic:
                resolved = self.resolver.resolve(state.intent.intent)
                state.allowed_skills = resolved.ids
                state.events.append(
                    RunEvent(
                        kind="skills_resolved",
                        detail={"resolver": self.resolver.name, "skills": resolved.ids},
                    )
                )
                planner_name = self.step_planner.name if self.step_planner else "none"
                state.plan = Plan(intent=state.intent.intent, steps=[], planner=planner_name)
                await self._execute_agentic(state)
            else:
                plan = self.planner.plan(query, state.intent)
                if len(plan.steps) > state.budget.max_steps:
                    self._finish(state, RunStatus.FAILED, "plan exceeds the step budget")
                else:
                    state.plan = plan
                    await self._execute(state)
            await self._respond(state)
            self.checkpoints.save(state)
            span.set("copilot.mode", state.mode)
            span.set("copilot.status", state.status.value)
            span.set("copilot.tool_calls", state.tool_calls)
        return state

    async def resume(self, run_id: str, *, approval_token: str) -> RunState:
        state = self.checkpoints.load(run_id)
        if state is None:
            raise KeyError(f"unknown run {run_id}")
        if state.status is not RunStatus.AWAITING_APPROVAL or state.pending_approval is None:
            raise ValueError("run is not awaiting approval")
        state.status = RunStatus.RUNNING
        # Time spent waiting for a human is not part of the run's execution budget.
        waited = round(time.time() - state.paused_at, 3) if state.paused_at else None
        state.started_at = time.time() - state.elapsed_s
        state.events.append(
            RunEvent(
                kind="resumed",
                detail={"step_id": state.pending_approval.step_id, "approval_wait_s": waited},
            )
        )
        if state.mode == "agentic" and self.step_planner is not None:
            await self._execute_agentic(state, approval_token=approval_token)
        else:
            await self._execute(state, approval_token=approval_token)
        await self._respond(state)
        self.checkpoints.save(state)
        return state

    # ── model accounting ────────────────────────────────────────────────────
    def _account(self, state: RunState, usage: ModelUsage | None, *, failed: bool = False) -> None:
        totals = state.model_usage
        if totals is None:
            return
        if usage is not None:
            totals.calls += 1
            totals.input_tokens += usage.input_tokens
            totals.output_tokens += usage.output_tokens
            totals.latency_ms = round(totals.latency_ms + usage.latency_ms, 2)
        if failed:
            totals.failures += 1

    def _model_failed(self, state: RunState, stage: str, exc: Exception) -> None:
        """Record a model failure and stop the run: there is no rules/template fallback."""
        self._account(state, None, failed=True)
        error = f"{type(exc).__name__}: {exc}"
        state.events.append(RunEvent(kind="model_failed", detail={"stage": stage, "error": error}))
        model = f"{self.llm.name}/{self.llm.model}" if self.llm else "the model"
        if isinstance(exc, ModelUnavailableError):
            message = (
                f"The language model ({model}) is unavailable, so I can't answer this request: "
                f"{exc}. Start the model server and try again."
            )
        else:
            message = (
                f"The language model ({model}) returned output I couldn't use while "
                f"{_STAGE_NAMES.get(stage, stage)}. Please try again."
            )
        done = sum(1 for r in state.results.values() if r.ok)
        if done:
            message += f" {done} step(s) had already run; their results are shown below."
        raise RunHaltError(RunStatus.FAILED, message)

    def _account_classifier(self, state: RunState) -> None:
        """Record intent-model usage and entities the grounding check dropped."""
        if not isinstance(self.classifier, LLMIntentClassifier):
            return
        self._account(state, self.classifier.last_usage)
        if self.classifier.dropped_entities:
            state.events.append(
                RunEvent(
                    kind="entities_dropped",
                    detail={"fields": self.classifier.dropped_entities, "reason": "ungrounded"},
                )
            )

    # ── agentic execution ───────────────────────────────────────────────────
    async def _execute_agentic(self, state: RunState, *, approval_token: str | None = None) -> None:
        if state.plan is None or state.intent is None or self.step_planner is None:
            raise RuntimeError("cannot run the agent loop without a plan and an intent")
        skills = [
            d
            for d in self.resolver.resolve(state.intent.intent).skills
            if d.id in state.allowed_skills
        ]
        decisions = rejections = 0
        try:
            while True:
                self._check_budget(state)
                if state.cursor < len(state.plan.steps):
                    step = state.plan.steps[state.cursor]  # resumed after approval
                else:
                    if len(state.plan.steps) >= state.budget.max_steps:
                        state.events.append(RunEvent(kind="step_budget_reached"))
                        break
                    if decisions >= state.budget.max_steps + 2 or rejections >= 3:
                        break
                    decisions += 1
                    try:
                        decision = await self.step_planner.next_step(state, skills)
                    except _MODEL_ERRORS as exc:
                        self._model_failed(state, "plan", exc)
                    self._account(state, self.step_planner.last_usage)
                    if decision.action == "finish":
                        state.events.append(
                            RunEvent(kind="plan_finish", detail={"thought": decision.thought[:300]})
                        )
                        break
                    planned, problem = self._validate_decision(state, decision)
                    if planned is None:
                        rejections += 1
                        state.events.append(
                            RunEvent(
                                kind="plan_rejected",
                                detail={"skill_id": decision.skill_id, "reason": problem},
                            )
                        )
                        continue
                    state.plan.steps.append(planned)
                    state.events.append(
                        RunEvent(
                            kind="plan_step",
                            detail={
                                "step_id": planned.step_id,
                                "skill_id": planned.skill_id,
                                "thought": decision.thought[:300],
                            },
                        )
                    )
                    step = planned
                token = (
                    approval_token
                    if state.pending_approval and state.pending_approval.step_id == step.step_id
                    else None
                )
                state.pending_approval = None
                result = await self._run_step(state, step, token, recoverable=True)
                if result is None:  # paused for approval
                    state.elapsed_s = round(time.time() - state.started_at, 4)
                    state.paused_at = time.time()
                    self.checkpoints.save(state)
                    return
                state.results[step.step_id] = result
                state.cursor += 1
                self.checkpoints.save(state)
            await self._reflect(state)
            self._compose(state)
        except RunHaltError as failure:
            self._finish(state, failure.status, failure.message)
        self.checkpoints.save(state)

    def _step_id(self, state: RunState, skill_id: str) -> str:
        base = _STEP_NAMES.get(skill_id, skill_id.replace(".", "_"))
        existing = {s.step_id for s in state.plan.steps} if state.plan else set()
        if base not in existing:
            return base
        n = 2
        while f"{base}_{n}" in existing:
            n += 1
        return f"{base}_{n}"

    def _validate_decision(
        self, state: RunState, decision: StepDecision
    ) -> tuple[PlanStep | None, str]:
        """Turn a model decision into a plan step, or explain why it is refused.

        Raises ``RunHaltError(NEEDS_CLARIFICATION)`` when a call lacks grounded values.
        """
        if state.intent is None:
            raise RunHaltError(RunStatus.FAILED, "run has no classified intent")
        skill_id = decision.skill_id
        if skill_id not in state.allowed_skills:
            return None, (
                f"skill '{skill_id}' is not available for intent {state.intent.intent.value}; "
                f"use one of {', '.join(state.allowed_skills)} or finish"
            )
        arguments = dict(decision.arguments)
        if skill_id == "token.inspect":
            if not state.intent.entities.jwt:
                return None, "the request contains no JWT to inspect"
            if arguments.get("token") not in (None, JWT_PLACEHOLDER):
                state.events.append(RunEvent(kind="argument_replaced", detail={"field": "token"}))
            arguments["token"] = state.intent.entities.jwt
        if skill_id in CALL_SKILLS:
            operation_id = str(arguments.get("operation_id", ""))
            described = self._described(state, operation_id)
            if described is None:
                return None, f"call api.describe for operation '{operation_id}' before invoking it"
            expected = str(described["invocation_skill"])
            if skill_id != expected:
                return None, f"operation '{operation_id}' must be invoked with {expected}"
            grounded = ground_call_arguments(
                arguments, described, state.query, state.intent.entities
            )
            state.events.append(
                RunEvent(
                    kind="arguments_grounded",
                    detail={
                        "operation_id": operation_id,
                        "dropped": grounded.dropped,
                        "overridden": grounded.overridden,
                        "missing": grounded.missing,
                    },
                )
            )
            if grounded.missing:
                state.missing_fields = grounded.missing
                raise RunHaltError(
                    RunStatus.NEEDS_CLARIFICATION,
                    f"To call {described['method']} {described['path']} I still need: "
                    + ", ".join(m.split(".", 1)[1] for m in grounded.missing)
                    + ".",
                )
            arguments = grounded.arguments
        for step in state.plan.steps if state.plan else []:
            done = state.results.get(step.step_id)
            if step.skill_id == skill_id and step.arguments == arguments and done and done.ok:
                return None, f"{skill_id} already ran with these arguments as [{step.step_id}]"
        step_id = self._step_id(state, skill_id)
        if skill_id in CALL_SKILLS:
            state.resolved_skills[step_id] = skill_id
        return (
            PlanStep(
                step_id=step_id,
                skill_id=skill_id,
                arguments=arguments,
                purpose=(decision.thought or skill_id)[:200],
            ),
            "",
        )

    @staticmethod
    def _described(state: RunState, operation_id: str | None) -> dict[str, Any] | None:
        for result in state.results.values():
            output = result.output
            if (
                result.ok
                and result.skill_id == "api.describe"
                and output is not None
                and (operation_id is None or output.get("operation_id") == operation_id)
            ):
                return output
        return None

    # ── response + UI ───────────────────────────────────────────────────────
    async def _respond(self, state: RunState) -> None:
        choices: list[tuple[str, str]] | None = None
        # Paused and failed runs keep the server's exact message (what will run, what is
        # missing, what failed): a model rewrite adds latency and no accuracy there.
        if (
            self.responder is not None
            and state.mode == "agentic"
            and state.status is RunStatus.COMPLETED
        ):
            try:
                message, choices = await self.responder.respond(state)
                self._account(state, self.responder.last_usage)
                if message:
                    state.message = message
            except _MODEL_ERRORS as exc:
                try:
                    self._model_failed(state, "respond", exc)
                except RunHaltError as failure:
                    self._finish(state, failure.status, failure.message)
        state.ui, rejected = build_components(state, choices)
        state.events.append(
            RunEvent(
                kind="ui",
                detail={
                    "components": [c.component for c in state.ui],
                    "chosen_by": "model" if choices is not None else "default",
                    "rejected": rejected,
                },
            )
        )

    # ── execution ────────────────────────────────────────────────────────────
    async def _execute(self, state: RunState, *, approval_token: str | None = None) -> None:
        if state.plan is None:
            raise RuntimeError("cannot execute a run without a plan")
        steps = state.plan.steps
        try:
            while state.cursor < len(steps):
                step = steps[state.cursor]
                self._check_budget(state)
                token = (
                    approval_token
                    if state.pending_approval and state.pending_approval.step_id == step.step_id
                    else None
                )
                state.pending_approval = None
                result = await self._run_step(state, step, token)
                if result is None:  # paused (approval or clarification)
                    state.elapsed_s = round(time.time() - state.started_at, 4)
                    state.paused_at = time.time()
                    self.checkpoints.save(state)
                    return
                state.results[step.step_id] = result
                state.cursor += 1
                self.checkpoints.save(state)
            await self._reflect(state)
            self._compose(state)
        except RunHaltError as failure:
            self._finish(state, failure.status, failure.message)
        self.checkpoints.save(state)

    def _check_budget(self, state: RunState) -> None:
        if state.tool_calls >= state.budget.max_tool_calls:
            raise RunHaltError(RunStatus.FAILED, "tool-call budget exhausted")
        if time.time() - state.started_at > state.budget.deadline_s:
            raise RunHaltError(RunStatus.FAILED, "run deadline exceeded")

    def _resolve(self, value: Any, state: RunState) -> Any:
        if isinstance(value, dict) and set(value) == {"$from", "path"}:
            source = state.results.get(value["$from"])
            if source is None or source.output is None:
                raise RunHaltError(RunStatus.FAILED, f"step '{value['$from']}' produced no output")
            try:
                return _lookup(source.output, value["path"])
            except KeyError:
                if value["$from"] == "search":
                    raise RunHaltError(
                        RunStatus.COMPLETED,
                        "I couldn't find an API operation matching that request.",
                    ) from None
                raise RunHaltError(RunStatus.FAILED, f"missing value {value['path']}") from None
        if isinstance(value, dict):
            return {k: self._resolve(v, state) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v, state) for v in value]
        return value

    async def _run_step(
        self,
        state: RunState,
        step: PlanStep,
        approval_token: str | None,
        *,
        recoverable: bool = False,
    ) -> SkillResult | None:
        skill_id = step.skill_id
        arguments = self._resolve(step.arguments, state)
        if skill_id == BIND_SKILL:
            described = state.results.get("describe")
            if described is None or described.output is None:
                raise RunHaltError(
                    RunStatus.FAILED, "cannot bind a call without an operation description"
                )
            skill_id = str(described.output["invocation_skill"])
            if skill_id not in CALL_SKILLS:
                raise RunHaltError(RunStatus.FAILED, f"refusing unexpected skill {skill_id}")
            if state.intent is None:
                raise RunHaltError(RunStatus.FAILED, "run has no classified intent")
            arguments, missing = bind_call_arguments(described.output, state.intent.entities)
            if missing:
                state.missing_fields = missing
                state.status = RunStatus.NEEDS_CLARIFICATION
                state.message = (
                    f"To call {described.output['method']} {described.output['path']} "
                    "I still need: " + ", ".join(m.split(".", 1)[1] for m in missing) + "."
                )
                return None
            state.resolved_skills[step.step_id] = skill_id

        descriptor = self.runtime.registry.get(skill_id)
        idempotency_key = None
        if descriptor is not None and descriptor.side_effect.requires_approval:
            idempotency_key = state.idempotency_keys.setdefault(
                step.step_id, f"{state.run_id}-{step.step_id}"
            )
        ctx = InvocationContext(
            principal=state.principal,
            environment=state.environment,
            correlation_id=f"{state.run_id}.{step.step_id}.{state.tool_calls + 1}",
            run_id=state.run_id,
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )
        state.tool_calls += 1
        result = await self.runtime.invoke(skill_id, arguments, ctx)
        state.events.append(
            RunEvent(
                kind="tool_call",
                detail={
                    "step_id": step.step_id,
                    "skill_id": skill_id,
                    "ok": result.ok,
                    "error": result.error.code.value if result.error else None,
                },
            )
        )
        if result.ok:
            return result
        if result.error is None:
            raise RunHaltError(RunStatus.FAILED, f"{skill_id} failed without an error")
        if result.error.code is SkillErrorCode.APPROVAL_REQUIRED:
            state.status = RunStatus.AWAITING_APPROVAL
            state.pending_approval = PendingApproval(
                step_id=step.step_id,
                skill_id=skill_id,
                action_hash=str(result.error.details["action_hash"]),
                environment=state.environment,
                summary=self._summarise_action(state, skill_id, arguments),
                arguments=redact(arguments),
            )
            state.message = f"Approval required: {state.pending_approval.summary}"
            return None
        if recoverable and result.error.code in _RECOVERABLE_CODES:
            return result  # an observation the planner can correct
        if result.error.code in _DENIAL_CODES:
            raise RunHaltError(RunStatus.REJECTED, f"Not permitted: {result.error.message}.")
        code = result.error.code.value.lower().replace("_", " ")
        advice = (
            f" It was attempted {result.attempts} time(s); this is usually temporary, so retry "
            f"later."
            if result.error.retryable
            else ""
        )
        raise RunHaltError(
            RunStatus.FAILED, f"{skill_id} failed ({code}): {result.error.message}.{advice}"
        )

    def _summarise_action(self, state: RunState, skill_id: str, arguments: dict[str, Any]) -> str:
        described = self._described(state, arguments.get("operation_id"))
        target = f"{described['method']} {described['path']}" if described else skill_id
        body = (
            json.dumps(redact(arguments.get("body")), sort_keys=True)
            if arguments.get("body")
            else "no body"
        )
        return f"{target} in '{state.environment}' with {body}"

    async def _reflect(self, state: RunState) -> None:
        """One bounded recovery step: explain upstream 4xx outcomes from documentation."""
        calls = [r for r in state.results.values() if r.skill_id in CALL_SKILLS and r.ok]
        call = calls[-1] if calls else None
        if (
            call is None
            or call.output is None
            or call.output.get("ok")
            or "explain" in state.results
        ):
            return
        if state.mode == "agentic" and any(
            r.skill_id == "docs.search" for r in state.results.values()
        ):
            return  # the planner already looked it up
        status = int(call.output.get("status_code", 0))
        hint = _UPSTREAM_HINTS.get(status)
        if (
            hint is None
            or state.tool_calls >= state.budget.max_tool_calls
            or "docs.search" not in self.runtime.registry
        ):
            return
        ctx = InvocationContext(
            principal=state.principal,
            environment=state.environment,
            correlation_id=f"{state.run_id}.reflect",
            run_id=state.run_id,
        )
        state.tool_calls += 1
        result = await self.runtime.invoke("docs.search", {"query": hint, "k": 3}, ctx)
        state.events.append(
            RunEvent(kind="reflection", detail={"status_code": status, "ok": result.ok})
        )
        if result.ok:
            state.results["explain"] = result

    # ── response composition ────────────────────────────────────────────────
    def _compose(self, state: RunState) -> None:
        if state.intent is None:
            raise RuntimeError("cannot compose a response without an intent")
        intent = state.intent.intent
        out = {k: v.output for k, v in state.results.items() if v.ok and v.output is not None}
        evidence: list[str] = []
        lines: list[str] = []
        if "search" in out and intent is Intent.API_DISCOVERY:
            hits = out["search"].get("results", [])
            if not hits:
                lines.append("I couldn't find an API operation matching that request.")
            for hit in hits[:5]:
                lines.append(
                    f"- {hit['operation_id']}: {hit['method']} {hit['path']} — {hit['summary']} "
                    f"(scopes: {', '.join(hit['scopes']) or 'none'})"
                )
                evidence.append(hit["source_id"])
        if "describe" in out and intent in (Intent.API_EXPLANATION, Intent.API_EXECUTION):
            d = out["describe"]
            evidence.append(f"openapi:{d['operation_id']}")
            if intent is Intent.API_EXPLANATION:
                required = [p["name"] for p in d["parameters"] if p["required"]]
                lines += [
                    f"{d['operation_id']} — {d['method']} {d['path']} ({d['api_title']} "
                    f"{d['api_version']})",
                    d["description"] or d["summary"],
                    f"Authentication: {d['authentication']}.",
                    f"Required parameters: {', '.join(required) or 'none'}.",
                    f"Request body required: {'yes' if d['request_body_required'] else 'no'}"
                    + (
                        f"; fields: {', '.join(d['request_body_schema'].get('required', []))}"
                        if d.get("request_body_schema")
                        else ""
                    ),
                    f"Responses: {', '.join(f'{c} {t}' for c, t in d['responses'].items())}.",
                ]
        if "codegen" in out:
            gen = out["codegen"]
            evidence.append(f"openapi:{gen['operation_id']}")
            for lang, snippet in gen["snippets"].items():
                lines.append(f"{lang}:\n{snippet}")
            lines += gen["notes"]
        if "call" in out:
            c = out["call"]
            evidence.append(f"correlation:{c['correlation_id']}")
            verdict = "succeeded" if c["ok"] else "was rejected by the API"
            lines.append(
                f"{c['method']} {c['path']} {verdict} with HTTP {c['status_code']} (correlation "
                f"id {c['correlation_id']})."
            )
            if c["ok"] and isinstance(c["response_body"], dict):
                summary = {
                    k: c["response_body"][k]
                    for k in ("id", "status", "amount", "currency", "count")
                    if k in c["response_body"]
                }
                if summary:
                    lines.append("Result: " + json.dumps(summary))
            if c.get("retry_after_s"):
                lines.append(f"Retry after {c['retry_after_s']} seconds.")
            lines.append("Equivalent cURL:\n" + c["curl"])
        for key in ("docs", "explain"):
            if key in out:
                answer = out[key]["answer"]
                lines.append(answer["text"])
                evidence += [cite["source_id"] for cite in answer.get("citations", [])]
        if "inspect" in out:
            t = out["inspect"]
            lines.append(
                f"Token: alg {t['algorithm']}, expires {t['expires_at'] or 'never'}, scopes "
                f"{', '.join(t['scopes']) or 'none'}."
            )
            lines += [f"- {issue}" for issue in t["issues"]] or ["- no problems detected"]
            lines.append(t["note"])
        if state.mode == "agentic":
            evidence = self._all_evidence(state)
        state.evidence = evidence
        self._finish(state, RunStatus.COMPLETED, "\n".join(line for line in lines if line))

    @staticmethod
    def _all_evidence(state: RunState) -> list[str]:
        evidence: list[str] = []
        for result in state.results.values():
            out = result.output or {}
            if not result.ok:
                continue
            if result.skill_id == "api.search":
                evidence += [hit["source_id"] for hit in out.get("results", [])[:5]]
            elif result.skill_id in ("api.describe", "code.generate"):
                evidence.append(f"openapi:{out['operation_id']}")
            elif result.skill_id in CALL_SKILLS and out.get("correlation_id"):
                evidence.append(f"correlation:{out['correlation_id']}")
            elif result.skill_id == "docs.search":
                evidence += [p["source_id"] for p in out.get("passages", [])]
        return list(dict.fromkeys(evidence))

    @staticmethod
    def _finish(state: RunState, status: RunStatus, message: str) -> RunState:
        state.status = status
        state.message = message
        state.elapsed_s = round(time.time() - state.started_at, 4) if state.started_at else 0.0
        return state
