"""In-process harness: real skills + real sandbox app over an in-process ASGI transport.

Nothing here mocks skill behaviour: requests go through the skill runtime, the SSRF
guard, the OAuth token flow and the sandbox's own scope/idempotency/validation logic.
Only DNS is faked (``sandbox.local`` → 127.0.0.1) because the sandbox runs in-process.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr

from ai.bootstrap import Services, Settings, build_services
from ai.knowledge.retrieval import Embedder
from ai.telemetry import SpanRecorder
from sandbox.app import SandboxConfig, create_app
from skills.api.gateway import GatewayEnvironment
from skills.runtime.audit import InMemoryAuditSink
from skills.runtime.contracts import InvocationContext, Principal

SANDBOX_HOST = "sandbox.local"


async def fake_resolver(host: str, port: int) -> list[str]:
    return {SANDBOX_HOST: ["127.0.0.1"], "api.example.com": ["93.184.216.34"]}.get(
        host, ["10.0.0.5"]
    )


@dataclass
class Harness:
    services: Services
    sandbox: SandboxConfig
    audit: InMemoryAuditSink
    recorder: SpanRecorder
    app: Any

    def ctx(
        self,
        *,
        subject: str = "alice",
        tenant: str = "acme",
        roles: frozenset[str] = frozenset({"developer"}),
        env: str = "sandbox",
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> InvocationContext:
        return InvocationContext(
            principal=Principal(subject=subject, tenant_id=tenant, roles=roles),
            environment=env,
            correlation_id=f"test_{uuid.uuid4().hex[:12]}",
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )


class FaultTransport(httpx.AsyncBaseTransport):
    """Injects sandbox faults (``X-Sandbox-Fault``) into the first N API requests.

    Token requests are untouched. Used by fault-injection tests and evaluations.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport, fault: str, times: int) -> None:
        self.inner, self.fault, self.remaining, self.api_calls = inner, fault, times, 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith("/oauth"):
            self.api_calls += 1
            if self.remaining > 0:
                self.remaining -= 1
                request.headers["X-Sandbox-Fault"] = self.fault
        return await self.inner.handle_async_request(request)


def build_harness(
    *,
    client_id: str = "acme-sandbox-app",
    environments: frozenset[str] = frozenset({"sandbox"}),
    fault: tuple[str, int] | None = None,
    embedder: Embedder | None = None,
) -> Harness:
    sandbox = SandboxConfig.default()
    app = create_app(sandbox)
    client = sandbox.clients[client_id]
    settings = Settings(
        runtime_mode="test",
        environments=environments,
        write_environments=frozenset({"sandbox"}),
        gateways={
            "sandbox": GatewayEnvironment(
                name="sandbox",
                base_url=f"http://{SANDBOX_HOST}",
                token_url=f"http://{SANDBOX_HOST}/oauth/token",
                client_id=client.client_id,
                client_secret=SecretStr(client.client_secret),
                kind="sandbox",
            )
        },
        insecure_local_gateways=frozenset({"sandbox"}),
    )
    audit = InMemoryAuditSink()
    recorder = SpanRecorder()
    transport: httpx.AsyncBaseTransport = httpx.ASGITransport(app=app)
    if fault is not None:
        transport = FaultTransport(transport, fault[0], fault[1])
    services = build_services(
        settings,
        transport=transport,
        resolver=fake_resolver,
        audit=audit,
        recorder=recorder,
        embedder=embedder,
    )
    return Harness(services=services, sandbox=sandbox, audit=audit, recorder=recorder, app=app)
