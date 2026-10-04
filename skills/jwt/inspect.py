"""JWT inspection: decode and explain, never verify or echo.

The skill decodes header and claims **without verifying the signature** and says so in
its output (``signature_verified`` is always ``False``). It reports common problems
(``alg: none``, missing or past ``exp``, very long lifetimes, missing scopes) and masks
subject-like claims. The token itself and its signature are never returned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field

from skills.runtime.contracts import InvocationContext, SideEffect, SkillDefinition
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.policy import TOKEN_INSPECT

_STANDARD = ("iss", "aud", "exp", "iat", "nbf", "azp", "client_id")
_MASKED = ("sub", "email", "preferred_username", "upn", "name")
MAX_LIFETIME_S = 24 * 3600


class InspectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=10, max_length=8192)
    required_scopes: list[str] = Field(default_factory=list, max_length=20)


class InspectOutput(BaseModel):
    algorithm: str | None
    key_id: str | None
    token_type: str | None
    claims: dict[str, Any]
    masked_claims: dict[str, str]
    other_claim_names: list[str]
    scopes: list[str]
    missing_scopes: list[str]
    expires_at: str | None
    issued_at: str | None
    expired: bool | None
    not_yet_valid: bool
    lifetime_s: int | None
    issues: list[str]
    signature_verified: bool = False
    note: str = "Decoded without signature verification; use the issuer's JWKS to verify."


def _mask(value: Any) -> str:
    text = str(value)
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _iso(ts: Any) -> str | None:
    if isinstance(ts, int | float):
        return datetime.fromtimestamp(ts, UTC).isoformat()
    return None


def build_jwt_skill(*, clock: Any = None) -> SkillDefinition[InspectInput, InspectOutput]:
    def now() -> float:
        return float(clock()) if clock else datetime.now(UTC).timestamp()

    async def inspect(inp: InspectInput, ctx: InvocationContext) -> InspectOutput:
        raw = inp.token.strip()
        if raw.lower().startswith("bearer "):
            raw = raw[7:].strip()
        try:
            header = jwt.get_unverified_header(raw)
            claims: dict[str, Any] = jwt.decode(
                raw, options={"verify_signature": False, "verify_exp": False, "verify_aud": False}
            )
        except jwt.PyJWTError as exc:
            raise SkillError(SkillErrorCode.INVALID_INPUT, "value is not a decodable JWT") from exc
        issues: list[str] = []
        alg = header.get("alg")
        if not alg or str(alg).lower() == "none":
            issues.append("unsigned token (alg 'none') — must be rejected by any API")
        elif str(alg).startswith("HS"):
            issues.append(
                "symmetric algorithm (HS*) — verifier must share the secret; prefer RS/ES/PS for "
                "third-party APIs"
            )
        exp, iat, nbf = claims.get("exp"), claims.get("iat"), claims.get("nbf")
        current = now()
        expired = bool(exp <= current) if isinstance(exp, int | float) else None
        if exp is None:
            issues.append("no 'exp' claim — token never expires")
        elif expired:
            issues.append("token is expired — a gateway will answer 401")
        not_yet_valid = isinstance(nbf, int | float) and nbf > current
        if not_yet_valid:
            issues.append("token is not yet valid ('nbf' in the future) — check clock skew")
        lifetime = (
            int(exp - iat)
            if isinstance(exp, int | float) and isinstance(iat, int | float)
            else None
        )
        if lifetime is not None and lifetime > MAX_LIFETIME_S:
            issues.append(f"very long lifetime ({lifetime // 3600}h)")
        raw_scope = claims.get("scope", claims.get("scp", []))
        scopes = (
            raw_scope.split() if isinstance(raw_scope, str) else [str(s) for s in raw_scope or []]
        )
        missing = [s for s in inp.required_scopes if s not in scopes]
        if missing:
            issues.append(
                "missing required scopes: " + ", ".join(missing) + " — a gateway will answer 403"
            )
        standard = {k: claims[k] for k in _STANDARD if k in claims}
        masked = {k: _mask(claims[k]) for k in _MASKED if k in claims}
        others = sorted(set(claims) - set(_STANDARD) - set(_MASKED) - {"scope", "scp"})
        return InspectOutput(
            algorithm=str(alg) if alg else None,
            key_id=str(header["kid"]) if header.get("kid") else None,
            token_type=str(header["typ"]) if header.get("typ") else None,
            claims=standard,
            masked_claims=masked,
            other_claim_names=others,
            scopes=scopes,
            missing_scopes=missing,
            expires_at=_iso(exp),
            issued_at=_iso(iat),
            expired=expired,
            not_yet_valid=not_yet_valid,
            lifetime_s=lifetime,
            issues=issues,
        )

    return SkillDefinition(
        id="token.inspect",
        name="Inspect JWT",
        version="1.0.0",
        description="Decode a JWT (without verifying it) and explain expiry, scopes and risky "
        "settings.",
        input_model=InspectInput,
        output_model=InspectOutput,
        handler=inspect,
        required_permissions=frozenset({TOKEN_INSPECT}),
        side_effect=SideEffect.NONE,
        timeout_s=2,
        error_codes=frozenset({SkillErrorCode.INVALID_INPUT}),
    )
