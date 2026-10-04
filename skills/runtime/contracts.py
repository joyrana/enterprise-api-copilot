"""Skill contract (ADR-0006).

A skill is a versioned capability with typed input/output, declared permissions,
side-effect class, timeout, retry policy, idempotency and audit requirements, and an
async handler. Handlers never see policy decisions; the runtime enforces them first.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from skills.runtime.errors import SkillErrorCode


class SideEffect(StrEnum):
    NONE = "NONE"  # pure computation (formatting, parsing)
    READ = "READ"  # reads external or stored data
    WRITE = "WRITE"  # creates/updates external state
    DESTRUCTIVE = "DESTRUCTIVE"  # deletes or irreversibly changes external state

    @property
    def requires_approval(self) -> bool:
        return self in (SideEffect.WRITE, SideEffect.DESTRUCTIVE)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, ge=1, le=5)
    initial_backoff_s: float = Field(default=0.2, ge=0)
    multiplier: float = Field(default=2.0, ge=1)
    max_backoff_s: float = Field(default=2.0, ge=0)

    def backoff(self, attempt: int) -> float:
        """Delay before ``attempt`` (1-based retry index)."""
        return min(self.initial_backoff_s * self.multiplier ** (attempt - 1), self.max_backoff_s)


class Principal(BaseModel):
    """Who is acting. Always supplied by the caller (platform), never by a model."""

    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    roles: frozenset[str] = frozenset()


class InvocationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    principal: Principal
    environment: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = None
    approval_token: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)

Handler = Callable[[InputT, InvocationContext], Awaitable[OutputT]]
# Side-effect-free validation run after policy and before approval, so humans are never
# asked to approve a request that cannot succeed. Raises SkillError on failure.
Preflight = Callable[[InputT, InvocationContext], Awaitable[None]]


class SkillDescriptor(BaseModel):
    """Public, side-effect-free description of a skill (used for discovery and MCP)."""

    id: str
    name: str
    version: str
    description: str
    side_effect: SideEffect
    required_permissions: list[str]
    requires_approval: bool
    idempotency_required: bool
    timeout_s: float
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    error_codes: list[str]


@dataclass(frozen=True)
class SkillDefinition(Generic[InputT, OutputT]):
    id: str
    name: str
    version: str
    description: str
    input_model: type[InputT]
    output_model: type[OutputT]
    handler: Handler[InputT, OutputT]
    required_permissions: frozenset[str]
    side_effect: SideEffect
    timeout_s: float = 10.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency_required: bool = False
    audit_required: bool = True
    error_codes: frozenset[SkillErrorCode] = frozenset()
    preflight: Preflight[InputT] | None = None

    def __post_init__(self) -> None:
        if self.side_effect.requires_approval and not self.idempotency_required:
            raise ValueError(f"skill {self.id}: side-effecting skills must require idempotency")
        if not self.required_permissions:
            raise ValueError(f"skill {self.id}: at least one permission is required")
        if self.timeout_s <= 0:
            raise ValueError(f"skill {self.id}: timeout must be positive")

    def descriptor(self) -> SkillDescriptor:
        return SkillDescriptor(
            id=self.id,
            name=self.name,
            version=self.version,
            description=self.description,
            side_effect=self.side_effect,
            required_permissions=sorted(self.required_permissions),
            requires_approval=self.side_effect.requires_approval,
            idempotency_required=self.idempotency_required,
            timeout_s=self.timeout_s,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.output_model.model_json_schema(),
            error_codes=sorted(c.value for c in self.error_codes),
        )


class SkillErrorInfo(BaseModel):
    code: SkillErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    skill_id: str
    skill_version: str
    ok: bool
    output: dict[str, Any] | None = None
    error: SkillErrorInfo | None = None
    attempts: int = 0
    duration_ms: float = 0.0
    correlation_id: str
    replayed: bool = False
    action_hash: str | None = None
