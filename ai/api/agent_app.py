"""Internal agent-service API (``contracts/openapi/agent-service.yaml``).

Called by the platform only. Every request needs a service token minted by the platform
(issuer ``copilot-platform``, audience ``copilot-agent``, lifetime ≤ 5 minutes) whose claims
carry the end-user principal. Approval tokens are created by the platform's approval
service; this API only forwards them to the skill runtime, which verifies them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ai.agent.orchestrator import CheckpointStore, Orchestrator
from ai.api.auth import TokenAuthority
from ai.api.http import endpoint, json, parse_body
from ai.api.platform_app import assert_principal
from ai.api.runs import RunService, RunView
from ai.bootstrap import Services
from skills.runtime.contracts import Principal

SERVICE_ISSUER = "copilot-platform"
SERVICE_AUDIENCE = "copilot-agent"
SERVICE_TOKEN_MAX_TTL_S = 300


class _Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    environment: str = Field(min_length=1, max_length=64)


class _Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_token: str = Field(min_length=10, max_length=4096)


def service_authority(key: bytes) -> TokenAuthority:
    return TokenAuthority(
        key, issuer=SERVICE_ISSUER, audience=SERVICE_AUDIENCE, max_ttl_s=SERVICE_TOKEN_MAX_TTL_S
    )


def create_agent_app(
    services: Services, *, service_key: bytes, store: CheckpointStore
) -> Starlette:
    authority = service_authority(service_key)
    runs = RunService(
        Orchestrator(services.runtime, checkpoints=store, telemetry=services.telemetry), store
    )

    async def health(request: Request, _: Principal | None) -> Response:
        return json({"status": "UP", "skills": len(services.registry)})

    async def start(request: Request, principal: Principal | None) -> Response:
        p = assert_principal(principal)
        body = await parse_body(request, _Start)
        return json(
            RunView.of(await runs.start(p, body.query, body.environment)).model_dump(mode="json"),
            201,
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
            request.path_params["run_id"], p.tenant_id, body.approval_token
        )
        return json(RunView.of(state).model_dump(mode="json"))

    return Starlette(
        routes=[
            Route("/internal/v1/health", endpoint(health, authority=None), methods=["GET"]),
            Route("/internal/v1/runs", endpoint(start, authority=authority), methods=["POST"]),
            Route(
                "/internal/v1/runs/{run_id}", endpoint(get, authority=authority), methods=["GET"]
            ),
            Route(
                "/internal/v1/runs/{run_id}/resume",
                endpoint(resume, authority=authority),
                methods=["POST"],
            ),
        ]
    )
