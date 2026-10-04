"""Policy decision point (PDP) interface and the local, deterministic implementation.

The skill runtime is the policy *enforcement* point. Decisions come from a
:class:`PolicyDecisionPort`. In production that port is backed by the Spring Boot
platform (ADR-0005). :class:`LocalPolicyEngine` is a dev/test implementation with an
explicit, read-only role → permission table.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from skills.runtime.contracts import Principal

# Permission vocabulary. Keep it small and explicit.
CATALOG_READ = "catalog:read"
DOCS_READ = "docs:read"
TOKEN_INSPECT = "token:inspect"  # noqa: S105 - permission name, not a credential
CODE_GENERATE = "code:generate"
API_INVOKE_READ = "api:invoke:read"
API_INVOKE_WRITE = "api:invoke:write"
API_INVOKE_DELETE = "api:invoke:delete"
APPROVAL_GRANT = "approval:grant"

_VIEWER = frozenset({CATALOG_READ, DOCS_READ, TOKEN_INSPECT, CODE_GENERATE})

DEFAULT_ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "viewer": _VIEWER,
        "developer": _VIEWER | {API_INVOKE_READ, API_INVOKE_WRITE},
        "approver": frozenset({APPROVAL_GRANT}),
        "admin": _VIEWER | {API_INVOKE_READ, API_INVOKE_WRITE, API_INVOKE_DELETE, APPROVAL_GRANT},
    }
)


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str
    missing_permissions: frozenset[str] = frozenset()


class PolicyDecisionPort(Protocol):
    async def decide(
        self, principal: Principal, permissions: frozenset[str], environment: str
    ) -> PolicyDecision: ...


class EnvironmentPolicy(BaseModel):
    """Which environments exist and which of them accept writes.

    Anything not listed is rejected before policy is even consulted. Production writes
    are disabled unless an environment is explicitly listed in ``write_enabled``.
    """

    model_config = ConfigDict(frozen=True)

    allowed: frozenset[str] = Field(default=frozenset({"sandbox"}))
    write_enabled: frozenset[str] = Field(default=frozenset({"sandbox"}))

    def is_allowed(self, environment: str) -> bool:
        return environment in self.allowed

    def writes_enabled(self, environment: str) -> bool:
        return environment in self.allowed and environment in self.write_enabled


class LocalPolicyEngine:
    """Deterministic RBAC for local development and tests. Not a production PDP."""

    def __init__(
        self,
        role_permissions: Mapping[str, Iterable[str]] = DEFAULT_ROLE_PERMISSIONS,
    ) -> None:
        self._roles: Mapping[str, frozenset[str]] = MappingProxyType(
            {role: frozenset(perms) for role, perms in role_permissions.items()}
        )

    def permissions_for(self, principal: Principal) -> frozenset[str]:
        granted: set[str] = set()
        for role in principal.roles:
            granted |= self._roles.get(role, frozenset())
        return frozenset(granted)

    async def decide(
        self, principal: Principal, permissions: frozenset[str], environment: str
    ) -> PolicyDecision:
        missing = permissions - self.permissions_for(principal)
        if missing:
            return PolicyDecision(
                allowed=False,
                reason=f"missing permissions: {', '.join(sorted(missing))}",
                missing_permissions=frozenset(missing),
            )
        return PolicyDecision(allowed=True, reason="all required permissions granted")
