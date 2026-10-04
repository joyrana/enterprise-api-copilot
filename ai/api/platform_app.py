"""Local reference implementation of ``contracts/openapi/platform-api.yaml`` (ADR-0009).

Development stand-in for the Spring Boot platform: it lets the CLI and web app run the
full workflow locally. It is refused outside ``local``/``test`` runtime modes. Catalog
reads go through the skill runtime, so the same permissions apply as for the agent.

Users authenticate with HS256 bearer tokens (audience ``copilot-platform``). In local
mode ``POST /api/v1/auth/dev-token`` issues them for configured synthetic users.
"""

from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import CheckpointStore, InMemoryCheckpointStore, Orchestrator
from ai.api.auth import TokenAuthority
from ai.api.http import ApiProblemError, endpoint, json, parse_body
from ai.api.runs import RunService, RunView
from ai.bootstrap import Services
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import InvocationContext, Principal
from skills.runtime.errors import SkillErrorCode
from skills.runtime.policy import LocalPolicyEngine

VERSION = "0.3.0"
PLATFORM_ISSUER = "copilot-platform"
PLATFORM_AUDIENCE = "copilot-platform"
DEFAULT_DEV_USERS = (
    "alice:acme:developer,priya:acme:approver,vic:acme:viewer,root:acme:admin,gina:globex:developer"
)


def parse_dev_users(spec: str) -> dict[str, Principal]:
    users: dict[str, Principal] = {}
    for entry in filter(None, (e.strip() for e in spec.split(","))):
        subject, tenant, roles = entry.split(":", 2)
        users[subject] = Principal(
            subject=subject, tenant_id=tenant, roles=frozenset(roles.split("+"))
        )
    return users


@dataclass
class PlatformConfig:
    token_key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    dev_users: dict[str, Principal] = field(
        default_factory=lambda: parse_dev_users(DEFAULT_DEV_USERS)
    )
    run_store: CheckpointStore | None = None
    default_environment: str = "sandbox"
    token_ttl_s: int = 3600

    @classmethod
    def from_env(cls) -> PlatformConfig:
        key = os.environ.get("COPILOT_PLATFORM_TOKEN_KEY")
        return cls(
            token_key=key.encode() if key else secrets.token_bytes(32),
            dev_users=parse_dev_users(os.environ.get("COPILOT_DEV_USERS", DEFAULT_DEV_USERS)),
            run_store=None,  # services.state (COPILOT_STATE_DB) is used when configured
        )


class _DevToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=128)


class _RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    environment: str = Field(default="sandbox", min_length=1, max_length=64)


class _Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Reject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


_SKILL_STATUS = {
    SkillErrorCode.FORBIDDEN: (403, "ACCESS_DENIED"),
    SkillErrorCode.NOT_FOUND: (404, "RESOURCE_NOT_FOUND"),
    SkillErrorCode.INVALID_INPUT: (400, "VALIDATION_ERROR"),
    SkillErrorCode.ENVIRONMENT_NOT_ALLOWED: (403, "ACCESS_DENIED"),
}


def create_platform_app(services: Services, config: PlatformConfig | None = None) -> Starlette:
    if services.settings.runtime_mode not in {"local", "test"}:
        raise RuntimeError("the local platform facade only runs in local/test mode (ADR-0009)")
    config = config or PlatformConfig()
    store: CheckpointStore = config.run_store or services.state or InMemoryCheckpointStore()
    authority = TokenAuthority(
        config.token_key,
        issuer=PLATFORM_ISSUER,
        audience=PLATFORM_AUDIENCE,
        max_ttl_s=config.token_ttl_s,
    )
    orchestrator = Orchestrator(services.runtime, checkpoints=store, telemetry=services.telemetry)
    approvals = ApprovalService(services.approval_signer, LocalPolicyEngine())
    runs = RunService(orchestrator, store, approvals)

    def _ctx(principal: Principal) -> InvocationContext:
        return InvocationContext(
            principal=principal,
            environment=config.default_environment,
            correlation_id=f"api_{uuid.uuid4().hex[:16]}",
        )

    async def _skill(
        skill_id: str, args: dict[str, object], principal: Principal
    ) -> dict[str, object]:
        result = await services.runtime.invoke(skill_id, args, _ctx(principal))
        if result.ok and result.output is not None:
            return result.output
        code = result.error.code if result.error else SkillErrorCode.INTERNAL_ERROR
        status, api_code = _SKILL_STATUS.get(
            code, (502 if code.value.startswith("UPSTREAM") else 500, code.value)
        )
        raise ApiProblemError(
            status, api_code, result.error.message if result.error else "skill failed"
        )

    def _run_json(state_view: RunView, status: int = 200) -> Response:
        return json(state_view.model_dump(mode="json"), status)

    async def health(request: Request, _: Principal | None) -> Response:
        return json(
            {
                "status": "UP",
                "service": "copilot-platform-local",
                "version": VERSION,
                "mode": "local-reference",
            }
        )

    async def dev_token(request: Request, _: Principal | None) -> Response:
        body = await parse_body(request, _DevToken)
        user = config.dev_users.get(body.subject)
        if user is None:
            raise ApiProblemError(403, "ACCESS_DENIED", "unknown development user")
        return json(
            {
                "access_token": authority.issue(user),
                "token_type": "Bearer",
                "expires_in": config.token_ttl_s,
            }
        )

    async def me(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json({"subject": p.subject, "tenant_id": p.tenant_id, "roles": sorted(p.roles)})

    async def skills(request: Request, principal: Principal | None) -> Response:
        assert_principal(principal)
        return json(
            {
                "skills": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "version": d.version,
                        "description": d.description,
                        "side_effect": d.side_effect.value,
                        "required_permissions": d.required_permissions,
                        "requires_approval": d.requires_approval,
                    }
                    for d in services.registry.descriptors()
                ]
            }
        )

    async def search(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        query = request.query_params.get("q", "")
        try:
            limit = int(request.query_params.get("limit", "5"))
        except ValueError as exc:
            raise ApiProblemError(400, "VALIDATION_ERROR", "limit must be an integer") from exc
        if not query or len(query) > 500 or not 1 <= limit <= 20:
            raise ApiProblemError(
                400, "VALIDATION_ERROR", "q is required (max 500 chars) and limit must be 1-20"
            )
        return json(await _skill("api.search", {"query": query, "limit": limit}, p))

    async def describe(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(
            await _skill("api.describe", {"operation_id": request.path_params["operation_id"]}, p)
        )

    async def create_run(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _RunCreate)
        state = await runs.start(p, body.query, body.environment)
        return _run_json(RunView.of(state), 201)

    async def list_runs(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        raw_status = request.query_params.get("status")
        try:
            status = RunStatus(raw_status) if raw_status else None
            limit = int(request.query_params.get("limit", "20"))
        except ValueError as exc:
            raise ApiProblemError(400, "VALIDATION_ERROR", "invalid status or limit") from exc
        if not 1 <= limit <= 100:
            raise ApiProblemError(400, "VALIDATION_ERROR", "limit must be 1-100")
        listed = runs.list(p.tenant_id, status=status, limit=limit)
        return json({"runs": [RunView.of(s).model_dump(mode="json") for s in listed]})

    async def get_run(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return _run_json(RunView.of(runs.get(request.path_params["run_id"], p.tenant_id)))

    async def approve(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Approve)
        return _run_json(
            RunView.of(await runs.approve(request.path_params["run_id"], p, body.action_hash))
        )

    async def reject(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Reject)
        return _run_json(
            RunView.of(await runs.reject(request.path_params["run_id"], p, body.reason))
        )

    public = {"authority": None}
    secured = {"authority": authority}
    app = Starlette(
        routes=[
            Route("/api/v1/health", endpoint(health, **public), methods=["GET"]),
            Route("/api/v1/auth/dev-token", endpoint(dev_token, **public), methods=["POST"]),
            Route("/api/v1/me", endpoint(me, **secured), methods=["GET"]),
            Route("/api/v1/skills", endpoint(skills, **secured), methods=["GET"]),
            Route("/api/v1/apis/search", endpoint(search, **secured), methods=["GET"]),
            Route("/api/v1/apis/{operation_id}", endpoint(describe, **secured), methods=["GET"]),
            Route("/api/v1/runs", endpoint(create_run, **secured), methods=["POST"]),
            Route("/api/v1/runs", endpoint(list_runs, **secured), methods=["GET"]),
            Route("/api/v1/runs/{run_id}", endpoint(get_run, **secured), methods=["GET"]),
            Route("/api/v1/runs/{run_id}/approve", endpoint(approve, **secured), methods=["POST"]),
            Route("/api/v1/runs/{run_id}/reject", endpoint(reject, **secured), methods=["POST"]),
        ]
    )
    app.state.authority = authority
    app.state.runs = runs
    return app


def assert_principal(principal: Principal | None) -> Principal:
    if principal is None:  # endpoint() guarantees this for secured routes
        raise ApiProblemError(401, "UNAUTHENTICATED", "authentication required")
    return principal
