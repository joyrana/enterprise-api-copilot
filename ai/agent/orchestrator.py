"""Bounded orchestrator: classify → plan → execute steps through the skill runtime.

Properties (tested in ``tests/unit/test_agent.py``):

* every tool call goes through ``SkillRuntime.invoke``; budgets cap steps, tool calls and
  wall-clock time;
* the environment comes from the caller and is never changed by request text;
* a side-effecting step without approval stops the run in ``AWAITING_APPROVAL`` with the
  exact action hash; ``resume`` continues from the checkpoint with an approval token and
  the *same* idempotency key;
* missing required arguments stop the run in ``NEEDS_CLARIFICATION`` instead of guessing;
* upstream 4xx outcomes trigger one bounded documentation lookup to explain the failure.

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
    PendingApproval,
    PlanStep,
    RunBudget,
    RunEvent,
    RunState,
    RunStatus,
)
from ai.agent.intent import IntentClassifier, RuleBasedIntentClassifier
from ai.agent.planner import BIND_SKILL, CALL_SKILLS, Planner, TemplatePlanner
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
        classifier: IntentClassifier | None = None,
        planner: Planner | None = None,
        checkpoints: CheckpointStore | None = None,
        budget: RunBudget | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.runtime = runtime
        self.classifier = classifier or RuleBasedIntentClassifier()
        self.planner = planner or TemplatePlanner()
        self.checkpoints = checkpoints or InMemoryCheckpointStore()
        self.budget = budget or RunBudget()
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
        with self.telemetry.span("agent.run", **{"copilot.run_id": state.run_id}) as span:
            state.intent = self.classifier.classify(query)
            state.events.append(
                RunEvent(
                    kind="intent",
                    detail={
                        "intent": state.intent.intent.value,
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
                return self._finish(
                    state,
                    RunStatus.REJECTED,
                    "I can't help with that request. " + state.intent.rationale + ".",
                )
            if state.intent.intent is Intent.CLARIFICATION_NEEDED:
                return self._finish(
                    state,
                    RunStatus.NEEDS_CLARIFICATION,
                    "Could you say more about what you want to do — for example which API, "
                    "resource or error?",
                )
            plan = self.planner.plan(query, state.intent)
            if len(plan.steps) > state.budget.max_steps:
                return self._finish(state, RunStatus.FAILED, "plan exceeds the step budget")
            state.plan = plan
            await self._execute(state)
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
        await self._execute(state, approval_token=approval_token)
        return state

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
        self, state: RunState, step: PlanStep, approval_token: str | None
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
        described = state.results.get("describe")
        target = (
            f"{described.output['method']} {described.output['path']}"
            if described and described.output
            else skill_id
        )
        body = (
            json.dumps(redact(arguments.get("body")), sort_keys=True)
            if arguments.get("body")
            else "no body"
        )
        return f"{target} in '{state.environment}' with {body}"

    async def _reflect(self, state: RunState) -> None:
        """One bounded recovery step: explain upstream 4xx outcomes from documentation."""
        call = state.results.get("call")
        if call is None or call.output is None or call.output.get("ok"):
            return
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
        out = {k: (v.output or {}) for k, v in state.results.items()}
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
        state.evidence = evidence
        self._finish(state, RunStatus.COMPLETED, "\n".join(line for line in lines if line))

    @staticmethod
    def _finish(state: RunState, status: RunStatus, message: str) -> RunState:
        state.status = status
        state.message = message
        state.elapsed_s = round(time.time() - state.started_at, 4) if state.started_at else 0.0
        return state
