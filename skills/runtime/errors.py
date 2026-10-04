"""Typed error contract shared by every skill.

Skills raise :class:`SkillError` with a :class:`SkillErrorCode`. The runtime converts
anything else into ``INTERNAL_ERROR`` without leaking the exception text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class SkillErrorCode(StrEnum):
    UNKNOWN_SKILL = "UNKNOWN_SKILL"
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    ENVIRONMENT_NOT_ALLOWED = "ENVIRONMENT_NOT_ALLOWED"
    FORBIDDEN = "FORBIDDEN"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    DESTINATION_BLOCKED = "DESTINATION_BLOCKED"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    TIMEOUT = "TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


RETRYABLE_CODES: frozenset[SkillErrorCode] = frozenset(
    {SkillErrorCode.TIMEOUT, SkillErrorCode.UPSTREAM_UNAVAILABLE}
)


class SkillError(Exception):
    """An expected, classified skill failure.

    ``message`` must be safe to show to a user and to a model: no secrets, no stack
    traces, no raw upstream bodies.
    """

    def __init__(
        self,
        code: SkillErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
