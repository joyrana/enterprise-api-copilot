"""Bearer-token authentication for the platform facade and the internal agent API.

* HS256 only, with the algorithm pinned on verification (no ``alg`` confusion, no ``none``).
* Required claims: ``iss``, ``aud``, ``sub``, ``tenant_id``, ``roles``, ``iat``, ``exp``.
* Lifetimes are bounded (``max_ttl_s``); verification allows 30 s clock skew.
* The principal is derived only from a verified token — never from request bodies.

Production identity comes from the platform's OIDC integration (Phase 3); the platform
then mints short-lived service tokens for the agent with :class:`TokenAuthority`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import jwt

from skills.runtime.contracts import Principal

ALGORITHM = "HS256"
MIN_KEY_BYTES = 32
REQUIRED_CLAIMS = ["iss", "aud", "sub", "tenant_id", "roles", "iat", "exp"]


class AuthError(Exception):
    pass


class TokenAuthority:
    def __init__(
        self,
        key: bytes,
        *,
        issuer: str,
        audience: str,
        max_ttl_s: int = 3600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(key) < MIN_KEY_BYTES:
            raise ValueError(f"signing key must be at least {MIN_KEY_BYTES} bytes")
        self._key = key
        self.issuer = issuer
        self.audience = audience
        self.max_ttl_s = max_ttl_s
        self._clock = clock

    def issue(self, principal: Principal, *, ttl_s: int | None = None) -> str:
        ttl = min(ttl_s or self.max_ttl_s, self.max_ttl_s)
        now = int(self._clock())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": principal.subject,
            "tenant_id": principal.tenant_id,
            "roles": sorted(principal.roles),
            "iat": now,
            "exp": now + ttl,
        }
        return jwt.encode(claims, self._key, algorithm=ALGORITHM)

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=[ALGORITHM],
                audience=self.audience,
                issuer=self.issuer,
                leeway=30,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("invalid or expired token") from exc
        if int(claims["exp"]) - int(claims["iat"]) > self.max_ttl_s:
            raise AuthError("token lifetime exceeds policy")
        roles = claims["roles"]
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            raise AuthError("malformed roles claim")
        try:
            return Principal(
                subject=str(claims["sub"]),
                tenant_id=str(claims["tenant_id"]),
                roles=frozenset(roles),
            )
        except ValueError as exc:
            raise AuthError("malformed principal claims") from exc


def bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    token = header[7:].strip()
    if not token:
        raise AuthError("missing bearer token")
    return token
