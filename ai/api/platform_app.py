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
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import CheckpointStore, InMemoryCheckpointStore, Orchestrator
from ai.api.auth import TokenAuthority
from ai.api.catalog import CatalogApi
from ai.api.http import ApiProblemError, endpoint, json, parse_body
from ai.api.runs import RunService, RunView
from ai.api.sse import stream_run
from ai.bootstrap import Services
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal
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
    conversation_id: str | None = Field(default=None, pattern=r"^conv_[0-9a-f]{16}$")


class _Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class _Approve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class _Reject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


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
    orchestrator = Orchestrator(
        services.runtime, llm=services.llm, checkpoints=store, telemetry=services.telemetry
    )
    approvals = ApprovalService(services.approval_signer, LocalPolicyEngine())
    runs = RunService(orchestrator, store, approvals)

    catalog = CatalogApi(services, config.default_environment)

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
        return json(catalog.skills())

    async def search(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(await catalog.search(request.query_params, p))

    async def describe(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(await catalog.describe(request.path_params["operation_id"], p))

    async def create_run(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _RunCreate)
        mode = request.query_params.get("mode", "sync")
        if mode not in ("sync", "async"):
            raise ApiProblemError(400, "VALIDATION_ERROR", "mode must be sync or async")
        if mode == "async":
            started = await runs.start_async(p, body.query, body.environment, body.conversation_id)
            return _run_json(RunView.of(started), 202)
        state = await runs.start(p, body.query, body.environment, body.conversation_id)
        return _run_json(RunView.of(state), 201)

    async def run_events(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        run_id = request.path_params["run_id"]
        return stream_run(
            lambda: runs.get(run_id, p.tenant_id),
            last_event_id=request.headers.get("last-event-id"),
        )

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

    def _conversation_json(conversation_id: str, p: Principal, status: int = 200) -> Response:
        conversation = runs.conversation_for(conversation_id, p)
        return json(
            {
                "conversation_id": conversation.conversation_id,
                "created_at": datetime.fromtimestamp(conversation.created_at, UTC).isoformat(),
                "created_by": conversation.created_by,
                "runs": [
                    RunView.of(s).model_dump(mode="json")
                    for s in runs.conversation_runs(conversation)
                ],
            },
            status,
        )

    async def create_conversation(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return _conversation_json(runs.create_conversation(p).conversation_id, p, 201)

    async def get_conversation(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return _conversation_json(request.path_params["conversation_id"], p)

    async def clarify(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Clarify)
        return _run_json(
            RunView.of(await runs.clarify(request.path_params["run_id"], p, body.message))
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
            Route("/api/v1/runs/{run_id}/events", endpoint(run_events, **secured), methods=["GET"]),
            Route("/api/v1/runs/{run_id}/clarify", endpoint(clarify, **secured), methods=["POST"]),
            Route(
                "/api/v1/conversations", endpoint(create_conversation, **secured), methods=["POST"]
            ),
            Route(
                "/api/v1/conversations/{conversation_id}",
                endpoint(get_conversation, **secured),
                methods=["GET"],
            ),
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
