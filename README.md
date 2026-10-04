# Enterprise API Copilot

**A governed AI agent for finding, understanding, testing and safely calling enterprise APIs. Every action passes policy checks, needs human approval before any write, and is covered by measured evaluations.**

[![Python CI](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/python-ci.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/python-ci.yml)
[![Go Build](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/go-build.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/go-build.yml)
[![Frontend Build](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/frontend-build.yml/badge.svg)](https://github.com/joyrana/enterprise-api-copilot/actions/workflows/frontend-build.yml)
![Python 3.12 | 3.13](https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB)
![Go 1.22+](https://img.shields.io/badge/go-1.22%2B-00ADD8)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

> [!WARNING]
> **Pre-release (0.2.0.dev).** The Python agent and skill runtime, the platform API's reference implementation and the Go CLI are implemented and tested. The Spring Boot backend, the full React build and the container images are **not built or verified yet**. Do not point this at production APIs. See [Project status](#project-status) for the evidence behind every claim.

---

## Contents

- [Why](#why)
- [What it does](#what-it-does)
- [Project status](#project-status)
- [Architecture](#architecture)
- [Security model](#security-model)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Evaluation](#evaluation)
- [Observability](#observability)
- [Repository layout](#repository-layout)
- [Development](#development)
- [Roadmap](#roadmap)
- [Contributing, security and license](#contributing-security-and-license)

---

## Why

Developers lose hours to API portals, sprawling docs and hand-written `curl` commands. Generic chat assistants make this worse in an enterprise. They invent endpoints and parameters, follow instructions hidden in documents, and treat "the model decided to" as permission.

This project is built around a different contract:

- **The model proposes; code decides.** Authorization, environment selection and approvals are enforced by a skill runtime outside the model ([principles](docs/architecture/principles.md)).
- **Nothing is invented.** If a required value such as a customer ID or an amount isn't in the request, the agent asks for it instead of guessing.
- **Writes need a human.** Every side-effecting call pauses for approval. The approval is bound to the exact action shown, can be used once and expires.
- **Claims are measured.** Capabilities ship with versioned datasets, confidence intervals and hard safety gates.

## What it does

```text
$ copilot ask "Create a payment of ₹500 for customer cust_acm0001"
[AWAITING_APPROVAL] run_effa574327574134  (sandbox, 3 tool calls)

Pending action (api.call.write in sandbox):
  POST /v1/payments in 'sandbox' with {"amount": 50000, "currency": "INR", "customer_id": "cust_acm0001"}
  action hash: 8ad006a5419f71fffe24de364e8daef6128177013c1674686bfec1d9ed8f2651
An approver can run:  copilot runs approve run_effa574327574134

$ copilot runs approve run_effa574327574134        # signed in as an approver
Requested by alice:
  POST /v1/payments in 'sandbox' with {"amount": 50000, "currency": "INR", "customer_id": "cust_acm0001"}
Approve exactly this action? [y/N] y
[COMPLETED] run_effa574327574134  (sandbox, 4 tool calls)

POST /v1/payments succeeded with HTTP 201 (correlation id run_effa574327574134.call.4).
Result: {"id": "pay_a9031c6aaa4c", "status": "authorized", "amount": 50000, "currency": "INR"}
Equivalent cURL:
curl -sS -X POST http://127.0.0.1:8090/v1/payments \
  -H "Authorization: Bearer $COPILOT_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: run_effa574327574134-call' \
  --data '{"amount":50000,"currency":"INR","customer_id":"cust_acm0001"}'

Evidence: openapi:createPayment, correlation:run_effa574327574134.call.4
```

*Real output from a local run against the synthetic sandbox, lightly trimmed. Amounts are in minor units (50000 paise = ₹500). The first command exits with code `3` (needs approval); the approval exits with `0`.*

| Capability | Example |
|---|---|
| **API discovery** across OpenAPI specs | "Which endpoint refunds a captured payment?" |
| **Explanation**: parameters, auth scopes, errors | "What does a 409 from orders mean?" |
| **Governed execution** through a gateway | Read calls run directly; writes pause for approval |
| **Troubleshooting from docs** with citations and abstention | "Why am I getting 429s?" (cites sources, says "I don't know" when the docs don't say) |
| **Code generation**: cURL, Python, JavaScript, Java (never embeds credentials) | "Give me a Python snippet for listing orders" |
| **JWT inspection**: decodes claims and never echoes the token | "Why is this token rejected?" |
| **MCP**: skills exposed as Model Context Protocol tools through the same runtime | Usable by MCP-capable agents |

## Project status

Status reflects code **with tests** in this repository. Full evidence, blockers and next steps: [`docs/implementation/STATUS.md`](docs/implementation/STATUS.md).

| Area | Status |
|---|---|
| Skill runtime: typed contracts, policy, action-bound approvals, idempotency, redacted audit | ✅ Implemented, tested |
| API skills against a synthetic sandbox gateway (OAuth, scopes, tenants, 429s, fault injection) | ✅ Implemented, tested end to end |
| Apigee runtime-proxy adapter (configured URL only, SSRF-safe) | ✅ Implemented · ⚠️ not tested against live Apigee |
| Documentation RAG: BM25 + LSA hybrid (RRF), tenant filtering, citations, abstention | ✅ In-process + PostgreSQL/pgvector SQL · pretrained embedder pending |
| Agent core: intent → bounded plan → execution, approval pause/resume | ✅ Deterministic core · 🚧 LangGraph adapter pending |
| Platform API ([OpenAPI](contracts/openapi/platform-api.yaml)) and agent API ([OpenAPI](contracts/openapi/agent-service.yaml)) | ✅ Reference implementation, contract-tested · 🚧 Spring Boot implementation pending |
| Durable state: runs, single-use approvals, idempotency | ✅ SQLite (survives restarts and concurrent processes) · PostgreSQL driver pending |
| Tracing: W3C `traceparent` from API → agent → skill → gateway | ✅ Implemented · OTel exporter pending |
| Go CLI | ✅ Implemented (standard library only), tested end to end |
| React web app: chat with approvals, run history | 🟡 Wired to the real API, client tested · npm build pending |
| Spring Boot backend, Helm chart, container images | 🚧 Scaffold / unverified |

Why some parts are pending: the environment these were built in blocked the PyPI, npm, Maven and Go package registries and had no Docker daemon. Nothing listed as pending has been claimed as working.

## Architecture

```mermaid
flowchart LR
  subgraph Clients
    CLI[Go CLI]
    Web[React app]
  end
  CLI --> Platform
  Web --> Platform
  Platform["Platform API<br/>identity · tenants · runs · approvals"]
  Platform -->|short-lived service token| Agent
  subgraph Agent["AI service (Python)"]
    Orchestrator["Intent → plan → bounded executor"]
    Knowledge["Retrieval · context · grounded answers"]
    Runtime["Skill runtime<br/>(policy enforcement point)"]
    Orchestrator --> Knowledge
    Orchestrator --> Runtime
  end
  Runtime -->|runtime calls only| Gateway["Apigee proxy<br/>or local sandbox"]
  Gateway --> APIs[(Enterprise / synthetic APIs)]
  Agent --> Store[(SQLite now · PostgreSQL + pgvector)]
  Platform --> Store
```

Every skill call goes through one path in the skill runtime:

> validate input → environment allowlist → policy decision → preflight → **approval check** (action hash, single use, expiry, separate approver for destructive actions) → idempotency → timeout/retry → output contract → redacted audit and trace span

Design records: [architecture overview](docs/architecture/overview.md) · [principles](docs/architecture/principles.md) · [technology baseline](docs/architecture/technology-baseline.md) · [ADRs](docs/adr/README.md).

## Security model

Built against an explicit [threat model](docs/security/threat-model.md) that covers prompt injection, cross-tenant access, SSRF, approval replay, token handling and more.

- **Untrusted content stays data.** Retrieved docs, OpenAPI descriptions, tool output and API responses are delimited, scanned for instruction-like text, and can never change policy, environment or approved arguments.
- **Approve what you saw.** The approver signs a hash of the exact request. Any change after approval invalidates it, and the database makes each approval single-use.
- **Least privilege by default.** Environments are read-only unless allowlisted for writes. The local policy engine refuses to run outside `local`/`test` mode.
- **Hardened auth.** JWTs use a pinned algorithm (no `alg:none`), with issuer and audience checks, required claims and a bounded lifetime. Service tokens are separate from user tokens.
- **Safe outbound HTTP.** Configured hosts only, private address ranges blocked, no redirects, plus timeouts and response-size caps.
- **No secrets in output.** Logs, audit events, traces and generated code are redacted. All test data is synthetic.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Getting started

### Prerequisites

| Tool | Needed for |
|---|---|
| Python 3.12 or 3.13 | AI service, sandbox, evaluations (required) |
| Go 1.22+ | CLI |
| Node.js 22+ | Web app client tests |
| PostgreSQL 16+ with pgvector | Optional integration tests |

### Install and verify (about two minutes, no credentials)

```bash
git clone https://github.com/joyrana/enterprise-api-copilot.git
cd enterprise-api-copilot

uv sync --extra dev             # or: python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

make lint-python                # ruff + strict mypy
make test-python                # unit, contract and system tests
make eval-smoke                 # evaluation with safety hard gates (non-zero exit on any violation)
```

### Run the full workflow locally

```bash
# 1 · synthetic gateway (dev-only secrets)
SANDBOX_CLIENT_SECRET=local-dev-secret-0123456789 make sandbox

# 2 · platform API, reference implementation (local mode only)
export COPILOT_GATEWAY_SANDBOX_BASE_URL=http://127.0.0.1:8090 \
       COPILOT_GATEWAY_SANDBOX_TOKEN_URL=http://127.0.0.1:8090/oauth/token \
       COPILOT_GATEWAY_SANDBOX_CLIENT_ID=acme-sandbox-app \
       COPILOT_GATEWAY_SANDBOX_CLIENT_SECRET=local-dev-secret-0123456789 \
       COPILOT_GATEWAY_SANDBOX_INSECURE_LOCAL=true \
       COPILOT_STATE_DB=.copilot/state.db \
       COPILOT_PLATFORM_TOKEN_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
make platform

# 3 · CLI
make build-cli && export PATH="$PWD/apps/cli/bin:$PATH"
copilot login --user alice                                          # developer
copilot ask "Create a payment of ₹500 for customer cust_acm0001"    # exit 3: needs approval
XDG_CONFIG_HOME=/tmp/priya copilot login --user priya               # approver
XDG_CONFIG_HOME=/tmp/priya copilot runs approve <run_id>
```

CLI exit codes are built for scripting: `0` ok · `1` error · `2` usage · `3` needs approval or clarification · `4` run rejected or failed. Add `--output json` for machine-readable output.

### Optional: PostgreSQL integration tests

```bash
docker compose -f docker/docker-compose.yml up -d postgres
COPILOT_TEST_PGURL=postgresql://api_copilot:dev-only-postgres-password@localhost:5432/api_copilot make test-python
```

## Configuration

Configuration uses environment variables (12-factor). Copy [`.env.example`](.env.example) and fill in values. Never commit real secrets.

| Variable | Purpose | Default |
|---|---|---|
| `COPILOT_RUNTIME_MODE` | `local`, `test` or a deployed mode. Dev-only components refuse to run outside `local`/`test` | `local` |
| `COPILOT_ENVIRONMENTS` / `COPILOT_WRITE_ENVIRONMENTS` | Environments the copilot may target / may write to | `sandbox` / `sandbox` |
| `COPILOT_APPROVAL_KEY` | HMAC key for approval tokens (≥32 random bytes) | random per process |
| `COPILOT_PLATFORM_TOKEN_KEY` / `COPILOT_SERVICE_TOKEN_KEY` | Signing keys for user and service-to-service tokens. Set them, or tokens stop working when the process restarts | random per process (local mode only) |
| `COPILOT_STATE_DB` | SQLite path for durable runs, approvals and idempotency (required by the agent service) | unset = in-memory |
| `COPILOT_GATEWAY_<ENV>_*` | Gateway base URL, token URL and client credentials for each environment | — |
| `COPILOT_TRACE_JSON` | `1` emits JSON-lines spans on the `copilot.trace` logger | off |
| `COPILOT_JUDGE_PROVIDER` / `COPILOT_JUDGE_MODEL` | Opt-in LLM judge for evaluations | off |

## Evaluation

Evaluation is offline-first, deterministic-first and versioned ([ADR-0008](docs/adr/ADR-0008.md), [details](docs/evaluation/README.md)). Reports record dataset hashes, configuration and per-example results with 95% bootstrap confidence intervals.

| Measure (synthetic data, local run) | Result |
|---|---|
| Agent task success, 38 tasks in 17 categories (incl. injection, cross-tenant, destructive) | **0.763** [0.632, 0.895] |
| Safety violations (hard gate) | **0** |
| Held-out retrieval, LSA + stemming vs. baseline (paired) | ΔMRR **+0.240** [+0.13, +0.36], 18 wins / 3 losses |
| Platform API load, read workload, c=1 / c=8 | 421 / 1021 req/s, 0 errors |

```bash
make eval-smoke                                  # PR gate
make eval-full                                   # all suites + ablations
python -m evals.ablation --split test            # paired comparison on the held-out split
python -m evals.judge calibrate                  # LLM-judge agreement on the calibration set
```

Settings are chosen on the `dev` split and reported on `test`. The live LLM-judge run has not been executed yet (it needs an API key).

## Observability

- **Tracing:** W3C Trace Context is accepted at the API, propagated through agent and skill spans, and forwarded to the gateway as `traceparent`. Responses echo `traceparent` and `X-Request-Id`.
- **Structured audit:** every skill call records who, what, where, the decision and the outcome, with secrets redacted.
- **Operations:** [runbook](docs/operations/runbook.md) · [release checklist](docs/operations/release-checklist.md). Prometheus, Grafana and OTel collector configs are in `observability/` (not yet verified end to end).

## Repository layout

```text
ai/              Python AI service
  agent/           intent, binding, planner, bounded orchestrator
  api/             platform API (reference) + internal agent API, auth, runs
  knowledge/       ingestion, chunking, retrieval (BM25 / LSA / RRF), answers, SQL
  models/          provider-neutral model interface (+ opt-in Anthropic provider)
  storage/         durable SQL runtime store (SQLite / PostgreSQL)
skills/          skill runtime (policy enforcement point) and skills: api, docs, jwt, MCP adapter
sandbox/         synthetic gateway, OpenAPI specs, public and tenant docs
evals/           datasets (v1, v2 dev/test), metrics, suites, ablations, judge, load test
contracts/       OpenAPI contracts (contract tests validate every response)
apps/cli/        Go CLI (standard library only)
apps/frontend/   React + TypeScript web app
apps/backend/    Spring Boot backend (scaffold)
tests/           unit · integration · contract · system
docs/            architecture, ADRs, security, evaluation, operations, implementation status
docker/ deployment/ observability/ apigee/   infrastructure (partly scaffold)
```

`platform/`, `sdk/` and `design/` currently hold design notes only.

## Development

| Task | Command |
|---|---|
| Lint, format check and type check (Python) | `make lint-python` |
| Format | `make fmt` |
| All tests / Python only | `make test` / `make test-python` |
| CLI tests | `make test-cli` |
| Web client tests (Node only) | `make test-frontend-client` |
| Load test against a running platform API | `make load-test` |
| List all targets | `make help` |

Conventions:

- **Contract-first.** Change `contracts/openapi/*.yaml` first. Contract tests fail on undocumented responses.
- **Decisions are recorded as ADRs** in [`docs/adr/`](docs/adr/README.md).
- **[Conventional Commits](https://www.conventionalcommits.org/)** (`feat:`, `fix:`, `docs:` …).
- **Evaluations gate behaviour changes.** A change that drops a safety gate or regresses a reported metric needs justification in the PR.
- **CI** pins third-party actions to commit SHAs and runs Python 3.12/3.13, PostgreSQL integration tests, evaluations, Go race tests, `golangci-lint` and `govulncheck`.

## Roadmap

Next steps, in order (details in [STATUS.md](docs/implementation/STATUS.md#exact-next-step)):

1. Lockfiles (`uv.lock`, `package-lock.json`, Maven wrapper) and PostgreSQL driver for the runtime store
2. LangGraph adapter with a PostgreSQL checkpointer
3. Spring Boot 4 implementation of the platform API, verified against the existing contract tests
4. Web app production build, component and accessibility tests, live evaluation dashboard
5. OpenTelemetry export, dashboards and verified container images
6. Live LLM-judge calibration with independently labelled items

## Contributing, security and license

- **Contributing:** read [CONTRIBUTING.md](CONTRIBUTING.md) and the [coding standards](docs/coding-standards.md). Issues labelled [`good first issue`](https://github.com/joyrana/enterprise-api-copilot/issues?q=label%3A%22good+first+issue%22) are a good place to start.
- **Security:** report vulnerabilities privately per [SECURITY.md](SECURITY.md). Do not open public issues for them.
- **Code of conduct:** [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- **License:** [Apache 2.0](LICENSE). Copyright 2026 Enterprise API Copilot Authors.
