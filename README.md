# Enterprise API Copilot

> **An Agentic AI Platform for Enterprise API Discovery, Testing, Troubleshooting and Automation.**

[![Java Build](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/java-build.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/java-build.yml)
[![Python CI](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/python-ci.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/python-ci.yml)
[![Go Build](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/go-build.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/go-build.yml)
[![Frontend Build](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/frontend-build.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/frontend-build.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

---

## Project Vision

Enterprise API Copilot transforms how developers interact with enterprise APIs. Instead of navigating complex API portals, reading sprawling documentation, or manually composing curl commands, developers can simply describe what they want in plain language — and the platform does the rest.

**Target experience** (illustrative — the CLI/web flow is not wired yet; the same workflow runs today through the Python agent core against the synthetic sandbox, with an approval step before the write):

```
Developer: "Create a sandbox payment worth ₹500 for customer ID cust_abc123"

Copilot:
  ✓ Understanding your request...
  ✓ Planning execution steps...
  ✓ Discovering API: POST /v1/payments
  ✓ Authenticating via Apigee (OAuth 2.0)...
  ✓ Executing API...
  ✓ Response received (HTTP 201)

Payment created successfully!
  ID:     pay_9xK2mNpQ
  Amount: ₹500.00
  Status: authorized

Equivalent curl:
  curl -X POST https://api.example.com/v1/payments \
    -H "Authorization: Bearer <token>" \
    -d '{"amount": 500, "currency": "INR", "customer": "cust_abc123"}'
```

The platform is designed for governed agentic workflows: API discovery, Apigee-mediated execution behind policy and human approval, troubleshooting from documentation, and code generation — with every capability measured by an offline evaluation suite.

---

## Status

> This is an early implementation. The table reflects what is built **and tested** in this
> repository today — see [`docs/implementation/STATUS.md`](docs/implementation/STATUS.md)
> for evidence and blockers, and [`docs/evaluation/README.md`](docs/evaluation/README.md)
> for measured results.

| Capability | Status |
|---|---|
| Skill runtime: typed contracts, policy enforcement, action-bound approvals, idempotency, audit | ✅ Implemented (Python, tested) |
| API discovery / explanation / execution against a synthetic sandbox gateway | ✅ Implemented (Python, tested end to end) |
| SSRF-safe gateway adapter for Apigee runtime proxies (configured URL only) | ✅ Implemented; ⚠️ not tested against a live Apigee environment |
| cURL / Python / JavaScript / Java snippet generation (no credentials embedded) | ✅ Implemented (snippets compiled/parsed in tests) |
| JWT inspection (decode-only, never echoes the token) | ✅ Implemented |
| Documentation RAG: hybrid BM25 + dense (RRF), tenant filtering, citations, abstention | ✅ In-process (LSA + stemming, chosen by held-out ablation) + PostgreSQL/pgvector SQL (tested); pretrained embedder pending |
| MCP server over the skill runtime (MCP Python SDK 2.x) | ✅ Implemented (tested in-process) |
| Agent core: intent → bounded plan → execution, approval pause/resume | ✅ Deterministic core + internal HTTP API with service-to-service auth; 🚧 LangGraph adapter pending |
| Evaluation platform with safety hard gates | ✅ Offline suites, 120-doc retrieval corpus with dev/test split and paired ablations, LLM-judge harness (live run opt-in), load test |
| Platform API (runs, approvals, catalog, skills) — [contract](contracts/openapi/platform-api.yaml) | ✅ Local reference implementation (dev only, contract-tested); 🚧 Spring Boot implementation pending |
| Durable state: runs, single-use approvals, idempotency | ✅ SQLite store (survives restarts and concurrent processes); PostgreSQL schema + statements verified, driver pending |
| Tracing | ✅ W3C `traceparent` from API request through agent/skill spans to the gateway; JSON span export |
| Go CLI (`ask`, `api search/describe`, `runs`, `approvals`, `skills list`, `doctor`, `login`, `eval run`) | ✅ Implemented on the standard library; tested end to end against real HTTP servers |
| React web app | 🟡 Chat (with approvals) and run history call the real API; client type-checked and tested; full build/tests pending npm access |
| Kubernetes / Helm | 🚧 Chart skeleton only |

---

## Architecture

```mermaid
graph TD
  Developer --> CLI
  Developer --> Frontend
  CLI --> Backend
  Frontend --> Backend
  Backend --> Supervisor
  Supervisor --> Planner
  Planner --> SkillRouter
  SkillRouter --> APISkill
  SkillRouter --> DocSkill
  SkillRouter --> JWTSkill
  APISkill --> Apigee
  Apigee --> ExternalAPI[Enterprise APIs]
  Backend --> Audit
  Backend --> Telemetry
```

### Key Design Principles

- **Hexagonal Architecture** — Domain logic is fully isolated from infrastructure concerns.
- **Domain-Driven Design** — Each bounded context owns its domain model.
- **Agent-Skill Separation** — Agents orchestrate; Skills execute. Skills are stateless MCP tools.
- **Backend as the Single Control Plane** — CLI and Frontend communicate only with the Backend; they never directly invoke agents or external systems.
- **The model is never an authority** — policy, approvals and environment selection are enforced outside the model ([principles](docs/architecture/principles.md)).

---

## Repository Structure

```
enterprise-api-copilot/
├── platform/
│   ├── auth/             # Identity and auth integrations
│   ├── gateway/          # API gateway controls
│   ├── config/           # Shared runtime configuration
│   ├── audit/            # Compliance and audit events
│   ├── telemetry/        # Tracing/metrics/log conventions
│   └── registry/         # Service and API registry assets
├── apps/
│   ├── backend/          # Spring Boot 3 backend (Java 21)
│   ├── frontend/         # React + TypeScript + Vite frontend
│   └── cli/              # Go CLI (standard library only)
├── ai/
│   ├── agent/            # Intent, planner, binding, bounded orchestrator
│   ├── api/              # Platform API (local reference) + internal agent API
│   ├── knowledge/        # Ingestion, retrieval (BM25/dense/RRF), context, answers, SQL
│   └── models/           # Provider-neutral model interface
├── skills/
│   ├── runtime/          # Contracts, policy, approvals, idempotency, audit, safe HTTP
│   ├── api/              # Search, describe, call, code generation, gateway adapter
│   ├── docs/             # Documentation search
│   ├── jwt/              # Token inspection
│   └── mcp_server.py     # MCP adapter over the runtime
├── evals/                # Datasets, metrics, suites, reports, load test
├── sandbox/              # Synthetic gateway, OpenAPI specs, docs
├── tests/                # Unit and integration tests
├── sdk/
│   ├── java/
│   ├── python/
│   ├── typescript/
│   └── go/
├── contracts/
│   ├── openapi/
│   ├── asyncapi/
│   └── json-schema/
├── observability/
│   ├── dashboards/
│   ├── otel/
│   ├── prometheus/
│   ├── grafana/
│   └── jaeger/
├── design/
│   ├── wireframes/
│   ├── sequence/
│   ├── component/
│   └── deployment/
├── apigee/               # Apigee proxy configuration and policies
├── deployment/           # Kubernetes manifests and Helm charts
├── docker/               # Dockerfiles and compose files
├── docs/                 # Architecture, ADRs, spring board, standards
├── examples/             # Example requests and integration demos
└── .github/              # CI/CD workflows, issue templates
```

> Canonical Python code: `ai/` (agent, knowledge, models), `skills/` (runtime + skills), `evals/`, `sandbox/`, `tests/`. Legacy `agents/` and hyphenated skill folders were removed (ADR-0005).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Java 21, Spring Boot 3.3 (EOL — migration to 4.1 planned), Maven |
| Database | PostgreSQL 17 + pgvector (Redis only until the backend drops it) |
| AI / Agents | Python 3.12+, Pydantic, MCP SDK 2.x; LangGraph adapter planned; provider-neutral model interface |
| Vector Store | PostgreSQL + pgvector (ADR-0007) |
| CLI | Go (standard library only, ADR-0009) |
| Frontend | React 18, TypeScript, Vite, TailwindCSS |
| API Gateway | Apigee X |
| Observability | OpenTelemetry, Prometheus, Grafana |
| Infrastructure | Docker, Kubernetes, Helm, GitHub Actions |
| Code Quality | Checkstyle, Spotless, ESLint, Prettier, golangci-lint |

---

## Quick Start

### Python AI service (works today, no credentials)

```bash
git clone https://github.com/joyrana/enterprise-api-copilot.git
cd enterprise-api-copilot
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

make lint-python test-python    # ruff, mypy --strict, pytest
make eval-smoke                 # evaluation with safety hard gates
make sandbox                    # synthetic gateway on http://127.0.0.1:8090
```

Optional pgvector SQL tests against a disposable database:

```bash
docker compose -f docker/docker-compose.yml up -d postgres
COPILOT_TEST_PGURL=postgresql://api_copilot:dev-only-postgres-password@localhost:5432/api_copilot pytest -m integration
```

### Full local workflow (CLI → platform API → agent → sandbox)

```bash
# terminal 1 — synthetic gateway (prints dev-only client secrets)
SANDBOX_CLIENT_SECRET=local-dev-secret-0123456789 make sandbox

# terminal 2 — local platform API (reference implementation, local mode only)
export COPILOT_GATEWAY_SANDBOX_BASE_URL=http://127.0.0.1:8090 \
       COPILOT_GATEWAY_SANDBOX_TOKEN_URL=http://127.0.0.1:8090/oauth/token \
       COPILOT_GATEWAY_SANDBOX_CLIENT_ID=acme-sandbox-app \
       COPILOT_GATEWAY_SANDBOX_CLIENT_SECRET=local-dev-secret-0123456789 \
       COPILOT_GATEWAY_SANDBOX_INSECURE_LOCAL=true
make platform

# terminal 3 — CLI (Go, no third-party modules)
make build-cli && export PATH="$PWD/apps/cli/bin:$PATH"
copilot login --user alice                      # developer
copilot ask "Create a payment of ₹500 for customer cust_acm0001"   # exits 3: needs approval
XDG_CONFIG_HOME=/tmp/priya copilot login --user priya              # approver
XDG_CONFIG_HOME=/tmp/priya copilot runs approve <run_id>           # shows the exact action first
```

The Spring Boot backend is still a scaffold (Maven Central was unreachable when this
was built); the React app's chat and history pages call the platform API but its npm
build has not been run yet. See `docs/implementation/STATUS.md`.

---

## Operations

See [docs/operations/runbook.md](docs/operations/runbook.md) and the
[release checklist](docs/operations/release-checklist.md).

---

## Spring Board

See [docs/spring-board.md](docs/spring-board.md) for milestone planning.

| Milestone | Focus |
|---|---|
| Milestone 1 | Foundation |
| Milestone 2 | Backend |
| Milestone 3 | CLI |
| Milestone 4 | AI |
| Milestone 5 | Skills |

Version milestones are tracked in [docs/milestones.md](docs/milestones.md).

---

## Developer Experience

See [docs/developer-experience.md](docs/developer-experience.md) for:

- Architecture references
- Coding standards
- Development workflow
- Branching strategy
- Commit convention
- Release strategy

---

## Contributing

We welcome contributions from the community. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/coding-standards.md](docs/coding-standards.md) before opening a pull request.

### Good First Issues

Look for issues tagged [`good first issue`](https://github.com/joyrana/enterprise-api-copilot/issues?q=label%3A%22good+first+issue%22) to get started.

---

## Security

Please review our [SECURITY.md](SECURITY.md) before reporting vulnerabilities. Do **not** open public GitHub issues for security bugs.

---

## License

Copyright 2026 Enterprise API Copilot Authors.

Licensed under the [Apache License, Version 2.0](LICENSE).
