"""Typed agent state: intents, plans, budgets and the checkpointable run state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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


class RunEvent(BaseModel):
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)


class RunState(BaseModel):
    run_id: str
    query: str = Field(repr=False)
    principal: Principal
    environment: str
    budget: RunBudget = Field(default_factory=RunBudget)
    status: RunStatus = RunStatus.RUNNING
    intent: IntentResult | None = None
    plan: Plan | None = None
    cursor: int = 0
    results: dict[str, SkillResult] = Field(default_factory=dict)
    resolved_skills: dict[str, str] = Field(default_factory=dict)
    idempotency_keys: dict[str, str] = Field(default_factory=dict)
    tool_calls: int = 0
    pending_approval: PendingApproval | None = None
    message: str = ""
    evidence: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    started_at: float = 0.0
    paused_at: float | None = None
    elapsed_s: float = 0.0
