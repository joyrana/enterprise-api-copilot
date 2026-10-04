"""Audit events for skill invocations. Arguments are always redacted before emission."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from skills.runtime.redaction import redact

_log = logging.getLogger("copilot.audit")


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = "skill.invocation"
    skill_id: str
    skill_version: str
    side_effect: str
    tenant_id: str
    subject: str
    environment: str
    correlation_id: str
    run_id: str | None = None
    outcome: str  # succeeded | failed | denied | replayed
    error_code: str | None = None
    action_hash: str | None = None
    approval_id: str | None = None
    approver: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0
    arguments: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def build(cls, *, arguments: dict[str, Any], **fields: Any) -> AuditEvent:
        return cls(arguments=redact(arguments), **fields)


class AuditSink(Protocol):
    async def emit(self, event: AuditEvent) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


class LoggingAuditSink:
    """Structured JSON audit lines on the ``copilot.audit`` logger."""

    async def emit(self, event: AuditEvent) -> None:
        _log.info(json.dumps(event.model_dump(mode="json"), sort_keys=True))
