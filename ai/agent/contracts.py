"""Typed agent state: intents, plans, budgets and the checkpointable run state."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from skills.runtime.contracts import Principal, SkillResult


class Intent(StrEnum):
    API_DISCOVERY = "api_discovery"
    API_EXPLANATION = "api_explanation"
    API_EXECUTION = "api_execution"
    TROUBLESHOOTING = "troubleshooting"
    TOKEN_INSPECTION = "token_inspection"  # noqa: S105 - intent label, not a credential
    CODE_GENERATION = "code_generation"
    DOCS_QUESTION = "docs_question"
    CLARIFICATION_NEEDED = "clarification_needed"
    UNSUPPORTED = "unsupported"


class Entities(BaseModel):
    payment_id: str | None = None
    customer_id: str | None = None
    order_id: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    status_codes: list[int] = Field(default_factory=list)
    environment: str | None = None
    languages: list[str] = Field(default_factory=list)
    jwt: str | None = Field(default=None, repr=False)
    operation_hint: str | None = None
    status_filter: str | None = None
    refund_reason: str | None = None


class IntentResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    entities: Entities = Field(default_factory=Entities)
    rationale: str
    classifier: str


class StepRef(BaseModel):
    """Reference to an earlier step's output, e.g. ``{"$from": "s1", "path": "results.0.id"}``."""

    model_config = ConfigDict(populate_by_name=True)
    from_step: str = Field(alias="$from")
    path: str


class PlanStep(BaseModel):
    step_id: str
    skill_id: str  # fixed id, or "@bind" for the API-call skill chosen from api.describe output
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str
    # Run by the orchestrator (e.g. the describe a proposed call needs), not chosen by the
    # model: it does not use the model's step budget, only the tool-call budget.
    auto: bool = False


class Plan(BaseModel):
    intent: Intent
    steps: list[PlanStep]
    planner: str


class RunBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_steps: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=8, ge=1, le=50)
    deadline_s: float = Field(default=60.0, gt=0)


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"  # declined: unsupported, unauthorized or disabled
    FAILED = "FAILED"


class PendingApproval(BaseModel):
    step_id: str
    skill_id: str
    action_hash: str
    environment: str
    summary: str
    arguments: dict[str, Any]  # redacted


class UIComponent(BaseModel):
    """A frontend component chosen for the response (``ai.agent.ui`` registry).

    ``props`` are always built server-side from real step output, never by a model.
    """

    id: str
    component: str
    source: str | None = None  # step id the props were built from
    props: dict[str, Any] = Field(default_factory=dict)


class ModelUsageTotals(BaseModel):
    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    failures: int = 0  # model calls that were unreachable or returned invalid output
    queue_wait_s: float = 0.0  # time spent waiting for a model slot (not part of the budget)


class HistoryTurn(BaseModel):
    """One earlier turn of a conversation, reduced to what later turns may use as context.

    ``user`` is what the user typed (redacted); ``assistant`` is the reply (redacted, cut
    to a budget). Neither is a grounding source except the user's own text.
    """

    run_id: str
    user: str
    assistant: str = ""
    intent: str | None = None
    operations: list[str] = Field(default_factory=list)
    entities: dict[str, Any] = Field(default_factory=dict)


class BlockedStep(BaseModel):
    """The model decision that stopped on missing values, kept so a clarification resumes it."""

    skill_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""


class RunEvent(BaseModel):
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class RunState(BaseModel):
    run_id: str
    # Monotonic origin of the current execution segment (not persisted). The run budget is
    # measured with it, so a wall-clock jump (sleep/wake, NTP step, VM pause) cannot end a
    # healthy run; ``started_at``/``elapsed_s`` stay wall-clock for display and persistence.
    _clock: float | None = PrivateAttr(default=None)
    query: str = Field(repr=False)
    principal: Principal
    environment: str
    budget: RunBudget = Field(default_factory=RunBudget)
    # "agentic": LLM intent → resolver → LLM step loop → LLM response + UI.
    # "deterministic": rules → template plan → template response (no model configured).
    mode: str = "deterministic"
    status: RunStatus = RunStatus.RUNNING
    intent: IntentResult | None = None
    plan: Plan | None = None
    allowed_skills: list[str] = Field(default_factory=list)  # from the intent resolver
    cursor: int = 0
    results: dict[str, SkillResult] = Field(default_factory=dict)
    resolved_skills: dict[str, str] = Field(default_factory=dict)
    idempotency_keys: dict[str, str] = Field(default_factory=dict)
    tool_calls: int = 0
    pending_approval: PendingApproval | None = None
    message: str = ""
    evidence: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ui: list[UIComponent] = Field(default_factory=list)
    model_usage: ModelUsageTotals | None = None
    events: list[RunEvent] = Field(default_factory=list)
    # Conversation memory (G1): bounded, redacted summary of earlier turns plus the text the
    # user typed in them. Context only; the typed text is the sole part used for grounding.
    conversation_id: str | None = None
    history: list[HistoryTurn] = Field(default_factory=list)
    prior_user_texts: list[str] = Field(default_factory=list)
    # Resumable clarification (G2): what the user answered, and the decision that was blocked.
    clarifications: list[str] = Field(default_factory=list)
    blocked: BlockedStep | None = None
    # Values bound from earlier API results (G3): step id -> field -> {step_id, path}.
    provenance: dict[str, dict[str, dict[str, str]]] = Field(default_factory=dict)
    # False while a run/resume/clarify segment is still producing its reply and UI (a status of
    # COMPLETED is visible before that); None for runs stored before the field existed.
    settled: bool | None = None
    started_at: float = 0.0
    paused_at: float | None = None
    elapsed_s: float = 0.0


def start_segment(state: RunState) -> None:
    """Begin (or continue after a pause) an execution segment of ``state``."""
    state._clock = time.monotonic() - state.elapsed_s
    state.started_at = time.time() - state.elapsed_s


def active_seconds(state: RunState) -> float:
    """Execution time of the run so far: monotonic within a segment, wall clock otherwise."""
    if state._clock is not None:
        return time.monotonic() - state._clock
    return time.time() - state.started_at if state.started_at else 0.0


def exclude_wait(state: RunState, seconds: float) -> None:
    """Remove ``seconds`` (e.g. queued for a model slot) from the run's execution time."""
    state.started_at += seconds
    if state._clock is not None:
        state._clock += seconds
