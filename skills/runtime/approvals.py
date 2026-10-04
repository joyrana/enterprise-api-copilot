"""Action-bound, expiring, single-use approvals (ADR-0006).

An approval authorizes exactly one action: a skill id + version, the exact arguments,
the environment, the tenant and the requesting subject. The token carries an HMAC over
those facts, an expiry and an id that can be consumed only once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from skills.runtime.errors import SkillError, SkillErrorCode

TOKEN_VERSION = "v1"  # noqa: S105 - format version, not a credential
MIN_KEY_BYTES = 32


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def action_hash(
    *,
    skill_id: str,
    skill_version: str,
    arguments: dict[str, Any],
    environment: str,
    tenant_id: str,
    subject: str,
) -> str:
    payload = {
        "skill_id": skill_id,
        "skill_version": skill_version,
        "arguments": arguments,
        "environment": environment,
        "tenant_id": tenant_id,
        "subject": subject,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


class ApprovalGrant(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    action_hash: str
    approver: str
    tenant_id: str
    issued_at: float
    expires_at: float


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class ApprovalSigner:
    def __init__(self, key: bytes, *, clock: Callable[[], float] = time.time) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(f"approval signing key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key
        self._clock = clock

    def issue(self, *, action: str, approver: str, tenant_id: str, ttl_s: float = 900.0) -> str:
        if ttl_s <= 0 or ttl_s > 24 * 3600:
            raise ValueError("approval ttl must be within (0, 24h]")
        now = self._clock()
        grant = ApprovalGrant(
            approval_id=secrets.token_urlsafe(16),
            action_hash=action,
            approver=approver,
            tenant_id=tenant_id,
            issued_at=now,
            expires_at=now + ttl_s,
        )
        body = _b64(canonical_json(grant.model_dump()).encode())
        signature = _b64(self._sign(body))
        return f"{TOKEN_VERSION}.{body}.{signature}"

    def verify(self, token: str, *, expected_action: str, tenant_id: str) -> ApprovalGrant:
        """Validate integrity, binding, tenant and expiry. Does **not** consume the token."""
        try:
            version, body, signature = token.split(".")
        except ValueError as exc:
            raise _invalid("malformed approval token") from exc
        if version != TOKEN_VERSION:
            raise _invalid("unsupported approval token version")
        try:
            given_signature = _unb64(signature)
        except (ValueError, TypeError) as exc:
            raise _invalid("malformed approval token") from exc
        if not hmac.compare_digest(self._sign(body), given_signature):
            raise _invalid("approval token signature mismatch")
        try:
            grant = ApprovalGrant.model_validate_json(_unb64(body))
        except (ValidationError, ValueError) as exc:
            raise _invalid("malformed approval token") from exc
        if not hmac.compare_digest(grant.action_hash, expected_action):
            raise _invalid(
                "approval does not match this action (arguments, environment or skill changed)"
            )
        if grant.tenant_id != tenant_id:
            raise _invalid("approval belongs to a different tenant")
        if self._clock() >= grant.expires_at:
            raise _invalid("approval expired")
        return grant

    def _sign(self, body: str) -> bytes:
        return hmac.new(self._key, f"{TOKEN_VERSION}.{body}".encode(), hashlib.sha256).digest()


def _invalid(message: str) -> SkillError:
    return SkillError(SkillErrorCode.APPROVAL_INVALID, message)


class ApprovalStore(Protocol):
    async def consume(self, approval_id: str, expires_at: float) -> bool:
        """Mark ``approval_id`` used. Return ``False`` if it was already used."""
        ...


class InMemoryApprovalStore:
    """Single-process single-use tracking. Tests and local runs only (not durable)."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._used: dict[str, float] = {}
        self._clock = clock

    async def consume(self, approval_id: str, expires_at: float) -> bool:
        now = self._clock()
        for key in [k for k, exp in self._used.items() if exp < now]:
            del self._used[key]
        if approval_id in self._used:
            return False
        self._used[approval_id] = expires_at
        return True
