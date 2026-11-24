"""Internal agent-service API (``contracts/openapi/agent-service.yaml``).

Called by the platform only. Every request needs a service token minted by the platform
(issuer ``copilot-platform``, audience ``copilot-agent``, lifetime ≤ 5 minutes) whose claims
carry the end-user principal. Approval tokens are created by the platform's approval
service; this API only forwards them to the skill runtime, which verifies them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ai.agent.contracts import RunStatus
from ai.agent.orchestrator import CheckpointStore, Orchestrator
from ai.api.auth import TokenAuthority
from ai.api.catalog import CatalogApi
from ai.api.http import ApiProblemError, endpoint, json, parse_body
from ai.api.platform_app import assert_principal
from ai.api.runs import RunService, RunView
from ai.api.sse import stream_run
from ai.bootstrap import Services
from skills.runtime.contracts import Principal

SERVICE_ISSUER = "copilot-platform"
SERVICE_AUDIENCE = "copilot-agent"
SERVICE_TOKEN_MAX_TTL_S = 300


class _Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    environment: str = Field(min_length=1, max_length=64)
    conversation_id: str | None = Field(default=None, pattern=r"^conv_[0-9a-f]{16}$")


class _Clarify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class _Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_token: str = Field(min_length=10, max_length=4096)
    approver: str | None = Field(default=None, min_length=1, max_length=128)


class _Reject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


def service_authority(key: bytes) -> TokenAuthority:
    return TokenAuthority(
        key, issuer=SERVICE_ISSUER, audience=SERVICE_AUDIENCE, max_ttl_s=SERVICE_TOKEN_MAX_TTL_S
    )


def create_agent_app(
    services: Services,
    *,
    service_key: bytes,
    store: CheckpointStore,
    default_environment: str = "sandbox",
) -> Starlette:
    authority = service_authority(service_key)
    catalog = CatalogApi(services, default_environment)
    runs = RunService(
        Orchestrator(
            services.runtime, llm=services.llm, checkpoints=store, telemetry=services.telemetry
        ),
        store,
    )

    async def health(request: Request, _: Principal | None) -> Response:
        return json({"status": "UP", "skills": len(services.registry)})

    async def start(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Start)
        mode = request.query_params.get("mode", "sync")
        if mode not in ("sync", "async"):
            raise ApiProblemError(400, "VALIDATION_ERROR", "mode must be sync or async")
        if mode == "async":
            started = await runs.start_async(p, body.query, body.environment, body.conversation_id)
            return json(RunView.of(started).model_dump(mode="json"), 202)
        state = await runs.start(p, body.query, body.environment, body.conversation_id)
        return json(RunView.of(state).model_dump(mode="json"), 201)

    async def events(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        run_id = request.path_params["run_id"]
        return stream_run(
            lambda: runs.get(run_id, p.tenant_id),
            last_event_id=request.headers.get("last-event-id"),
        )

    async def get(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(
            RunView.of(runs.get(request.path_params["run_id"], p.tenant_id)).model_dump(mode="json")
        )

    async def resume(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Resume)
        state = await runs.resume_with_token(
            request.path_params["run_id"], p.tenant_id, body.approval_token, body.approver
        )
        return json(RunView.of(state).model_dump(mode="json"))

    async def reject(request: Request, principal: Principal | None) -> Response:
        # The platform vetted the approver's role; the token's principal is the approver.
        p = assert_principal(principal)
        body = await parse_body(request, _Reject)
        state = await runs.reject(request.path_params["run_id"], p, body.reason)
        return json(RunView.of(state).model_dump(mode="json"))

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

    def conversation_json(conversation_id: str, p: Principal, status: int = 200) -> Response:
        conversation = runs.get_conversation(conversation_id, p.tenant_id)
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
        return conversation_json(runs.create_conversation(p).conversation_id, p, 201)

    async def get_conversation(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return conversation_json(request.path_params["conversation_id"], p)

    async def skills(request: Request, principal: Principal | None) -> Response:
        assert_principal(principal)
        return json(catalog.skills())

    async def search(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(await catalog.search(request.query_params, p))

    async def describe(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        return json(await catalog.describe(request.path_params["operation_id"], p))

    async def clarify(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Clarify)
        state = await runs.clarify(request.path_params["run_id"], p, body.message)
        return json(RunView.of(state).model_dump(mode="json"))

    return Starlette(
        routes=[
            Route("/internal/v1/health", endpoint(health, authority=None), methods=["GET"]),
            Route("/internal/v1/runs", endpoint(start, authority=authority), methods=["POST"]),
            Route("/internal/v1/runs", endpoint(list_runs, authority=authority), methods=["GET"]),
            Route("/internal/v1/skills", endpoint(skills, authority=authority), methods=["GET"]),
            Route(
                "/internal/v1/apis/search", endpoint(search, authority=authority), methods=["GET"]
            ),
            Route(
                "/internal/v1/apis/{operation_id}",
                endpoint(describe, authority=authority),
                methods=["GET"],
            ),
            Route(
                "/internal/v1/conversations",
                endpoint(create_conversation, authority=authority),
                methods=["POST"],
            ),
            Route(
                "/internal/v1/conversations/{conversation_id}",
                endpoint(get_conversation, authority=authority),
                methods=["GET"],
            ),
            Route(
                "/internal/v1/runs/{run_id}/reject",
                endpoint(reject, authority=authority),
                methods=["POST"],
            ),
            Route(
                "/internal/v1/runs/{run_id}", endpoint(get, authority=authority), methods=["GET"]
            ),
            Route(
                "/internal/v1/runs/{run_id}/events",
                endpoint(events, authority=authority),
                methods=["GET"],
            ),
            Route(
                "/internal/v1/runs/{run_id}/clarify",
                endpoint(clarify, authority=authority),
                methods=["POST"],
            ),
            Route(
                "/internal/v1/runs/{run_id}/resume",
                endpoint(resume, authority=authority),
                methods=["POST"],
            ),
        ]
    )
