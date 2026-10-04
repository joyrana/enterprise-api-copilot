"""Composition root: settings → gateway → catalog/knowledge → skills → runtime.

Configuration is read from environment variables (see ``.env.example``):

``COPILOT_RUNTIME_MODE``     ``local`` | ``test`` | ``production`` (default ``local``)
``COPILOT_APPROVAL_KEY``     ≥32-byte secret; required unless mode is local/test, where a
                             random per-process key is generated (approvals then do not
                             survive restarts)
``COPILOT_ENVIRONMENTS``     comma list of enabled environments (default ``sandbox``)
``COPILOT_WRITE_ENVIRONMENTS`` comma list accepting writes (default ``sandbox``)
``COPILOT_GATEWAY_<ENV>_BASE_URL`` / ``_TOKEN_URL`` / ``_CLIENT_ID`` / ``_CLIENT_SECRET``
``COPILOT_STATE_DB``         SQLite path for durable runs, single-use approvals and
                             idempotency (in-memory when unset)
``COPILOT_GATEWAY_<ENV>_INSECURE_LOCAL`` ``true`` to allow plain-HTTP/private address for a
                             local sandbox host only
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, SecretStr

from ai.knowledge.documents import PUBLIC_TENANT
from ai.knowledge.ingest import Ingestor, read_markdown_tree
from ai.knowledge.openapi import load_spec
from ai.knowledge.retrieval import Embedder, HashingEmbedder, KnowledgeIndex, LSAEmbedder
from ai.knowledge.text import tokenize, tokenize_stemmed
from ai.storage.sql_store import SqlRuntimeStore
from ai.telemetry import SpanRecorder, Telemetry
from skills.api.catalog import ApiCatalog
from skills.api.gateway import ApiGateway, GatewayEnvironment
from skills.api.skills import build_api_skills
from skills.docs.search import build_docs_skill
from skills.jwt.inspect import build_jwt_skill
from skills.runtime.approvals import ApprovalSigner, InMemoryApprovalStore
from skills.runtime.audit import AuditSink, InMemoryAuditSink, LoggingAuditSink
from skills.runtime.http_safety import OutboundPolicy, Resolver, SafeHttpClient, system_resolver
from skills.runtime.idempotency import InMemoryIdempotencyStore
from skills.runtime.policy import EnvironmentPolicy, LocalPolicyEngine, PolicyDecisionPort
from skills.runtime.registry import SkillRegistry
from skills.runtime.runtime import SkillRuntime

REPO_ROOT = Path(__file__).resolve().parent.parent
SANDBOX_DIR = REPO_ROOT / "sandbox"


class Settings(BaseModel):
    runtime_mode: str = "local"
    approval_key: SecretStr | None = None
    environments: frozenset[str] = frozenset({"sandbox"})
    write_environments: frozenset[str] = frozenset({"sandbox"})
    gateways: dict[str, GatewayEnvironment] = Field(default_factory=dict)
    insecure_local_gateways: frozenset[str] = frozenset()
    spec_paths: list[Path] = Field(
        default_factory=lambda: sorted((SANDBOX_DIR / "specs").glob("*.yaml"))
    )
    # Documentation index configuration. "lsa"+"stem" was selected by the v2 retrieval
    # ablation (held-out test ΔMRR +0.24, see docs/evaluation/README.md). The API catalog
    # keeps the hashing/plain baseline: its ablation was inconclusive.
    docs_embedder: str = "lsa"  # lsa | hashing
    docs_analyzer: str = "stem"  # stem | plain
    public_docs_dir: Path | None = SANDBOX_DIR / "docs" / "public"
    tenant_docs_dir: Path | None = SANDBOX_DIR / "docs" / "tenants"
    state_db: Path | None = None  # durable runs/approvals/idempotency (SQLite); None = in-memory
    max_response_bytes: int = 1_000_000
    http_timeout_s: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)

        def split(name: str, default: str) -> frozenset[str]:
            return frozenset(x.strip() for x in env.get(name, default).split(",") if x.strip())

        environments = split("COPILOT_ENVIRONMENTS", "sandbox")
        gateways: dict[str, GatewayEnvironment] = {}
        insecure: set[str] = set()
        for name in environments:
            prefix = f"COPILOT_GATEWAY_{name.upper()}_"
            if f"{prefix}BASE_URL" not in env:
                continue
            gateways[name] = GatewayEnvironment(
                name=name,
                base_url=env[f"{prefix}BASE_URL"],
                token_url=env[f"{prefix}TOKEN_URL"],
                client_id=env[f"{prefix}CLIENT_ID"],
                client_secret=SecretStr(env[f"{prefix}CLIENT_SECRET"]),
                kind=env.get(f"{prefix}KIND", "apigee-runtime"),
            )
            if env.get(f"{prefix}INSECURE_LOCAL", "").lower() == "true":
                insecure.add(name)
        key = env.get("COPILOT_APPROVAL_KEY")
        return cls(
            runtime_mode=env.get("COPILOT_RUNTIME_MODE", "local"),
            approval_key=SecretStr(key) if key else None,
            environments=environments,
            write_environments=split("COPILOT_WRITE_ENVIRONMENTS", "sandbox"),
            gateways=gateways,
            insecure_local_gateways=frozenset(insecure),
            state_db=Path(env["COPILOT_STATE_DB"]) if env.get("COPILOT_STATE_DB") else None,
        )


@dataclass
class Services:
    settings: Settings
    registry: SkillRegistry
    runtime: SkillRuntime
    catalog: ApiCatalog
    knowledge: KnowledgeIndex
    ingestor: Ingestor
    gateway: ApiGateway
    approval_signer: ApprovalSigner
    audit: AuditSink
    telemetry: Telemetry
    state: SqlRuntimeStore | None = None


def _outbound_policy(settings: Settings) -> OutboundPolicy:
    hosts: set[str] = set()
    ports: set[int] = {443}
    insecure: set[str] = set()
    for name, gw in settings.gateways.items():
        for url in (gw.base_url, gw.token_url):
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            hosts.add(host)
            ports.add(parts.port or (443 if parts.scheme == "https" else 80))
            if name in settings.insecure_local_gateways:
                insecure.add(host)
    return OutboundPolicy(
        allowed_hosts=frozenset(hosts),
        allowed_ports=frozenset(ports),
        insecure_http_hosts=frozenset(insecure),
        private_network_hosts=frozenset(insecure),
        max_response_bytes=settings.max_response_bytes,
        timeout_s=settings.http_timeout_s,
    )


def _signing_key(settings: Settings) -> bytes:
    if settings.approval_key is not None:
        return settings.approval_key.get_secret_value().encode()
    if settings.runtime_mode in {"local", "test"}:
        return secrets.token_bytes(32)
    raise RuntimeError("COPILOT_APPROVAL_KEY is required outside local/test mode")


def build_services(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = system_resolver,
    policy: PolicyDecisionPort | None = None,
    embedder: Embedder | None = None,
    audit: AuditSink | None = None,
    recorder: SpanRecorder | None = None,
) -> Services:
    if policy is None and settings.runtime_mode not in {"local", "test"}:
        raise RuntimeError(
            "a platform policy decision point is required outside local/test mode; "
            "LocalPolicyEngine is a development stand-in (ADR-0005)"
        )
    telemetry = Telemetry(recorder)
    state = SqlRuntimeStore.sqlite(settings.state_db) if settings.state_db else None
    http = SafeHttpClient(_outbound_policy(settings), transport=transport, resolver=resolver)
    gateway = ApiGateway(settings.gateways, http)

    catalog = ApiCatalog(embedder)
    for path in settings.spec_paths:
        catalog.register(
            load_spec(path.read_text(encoding="utf-8"), api_id=path.stem), tenant_id=PUBLIC_TENANT
        )

    if embedder is not None:
        knowledge = KnowledgeIndex(embedder)
    else:
        analyzer = tokenize_stemmed if settings.docs_analyzer == "stem" else tokenize
        docs_embedder: Embedder = (
            LSAEmbedder(analyzer=analyzer)
            if settings.docs_embedder == "lsa"
            else HashingEmbedder(analyzer=analyzer)
        )
        knowledge = KnowledgeIndex(docs_embedder, analyzer=analyzer)
    ingestor = Ingestor(knowledge)
    if settings.public_docs_dir and settings.public_docs_dir.is_dir():
        docs, _ = read_markdown_tree(settings.public_docs_dir, tenant_id=PUBLIC_TENANT)
        ingestor.ingest(docs)
    if settings.tenant_docs_dir and settings.tenant_docs_dir.is_dir():
        for tenant_dir in sorted(p for p in settings.tenant_docs_dir.iterdir() if p.is_dir()):
            docs, _ = read_markdown_tree(tenant_dir, tenant_id=tenant_dir.name)
            # Prefix doc ids with the tenant so identical file names never collide.
            ingestor.ingest(
                [d.model_copy(update={"doc_id": f"{tenant_dir.name}/{d.doc_id}"}) for d in docs]
            )

    registry = SkillRegistry()
    for skill in build_api_skills(catalog, gateway):
        registry.register(skill)
    registry.register(build_jwt_skill())
    registry.register(build_docs_skill(knowledge))

    signer = ApprovalSigner(_signing_key(settings))
    audit_sink = audit or (
        InMemoryAuditSink() if settings.runtime_mode == "test" else LoggingAuditSink()
    )
    runtime = SkillRuntime(
        registry=registry,
        policy=policy or LocalPolicyEngine(),
        environments=EnvironmentPolicy(
            allowed=settings.environments, write_enabled=settings.write_environments
        ),
        approval_signer=signer,
        approval_store=state if state is not None else InMemoryApprovalStore(),
        idempotency_store=state if state is not None else InMemoryIdempotencyStore(),
        audit_sink=audit_sink,
        telemetry=telemetry,
    )
    return Services(
        settings=settings,
        registry=registry,
        runtime=runtime,
        catalog=catalog,
        knowledge=knowledge,
        ingestor=ingestor,
        gateway=gateway,
        approval_signer=signer,
        audit=audit_sink,
        telemetry=telemetry,
        state=state,
    )
