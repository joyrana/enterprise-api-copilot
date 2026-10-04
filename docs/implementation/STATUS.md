# Implementation Status

- **Last updated:** 2026-10-04 (session 3)
- **Base commit:** `2e5ef5b`. All work from sessions 1–3 is on branch `feat/agentic-platform-foundation` with a pull request against `main`.
- **Plan:** [`MASTER_PLAN.md`](MASTER_PLAN.md) · **Baseline audit:** [`AUDIT.md`](AUDIT.md)

## External blocker (read first)

The environment's egress policy blocks **PyPI, npm, Maven Central and the Go module proxy**
(re-checked 2026-10-04: still 403). Consequences:

- Spring Boot backend **not built or tested**; LangGraph, FastAPI, psycopg **not installed**.
- No `uv.lock` / `package-lock.json` / Maven wrapper. (The Go CLI no longer needs a `go.sum`.)
- The React app's full npm build, Vitest and ESLint have **not run**.

Work was therefore limited to what could be verified with local tooling: Python 3.13 with
pydantic/starlette/uvicorn/httpx/mcp 2.2/numpy/jsonschema/PyJWT, pytest, ruff, mypy, Go 1.24,
Node 22 + global TypeScript 6.0 and Prettier, `javac`, PostgreSQL 16 + pgvector 0.8.7 (built from source).

**To unblock:** allow `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`,
`repo.maven.apache.org` (and `proxy.golang.org`, `sum.golang.org` for `govulncheck`).

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| 0 Audit & baseline | **Done** | `AUDIT.md`, ADR-0005…0009, architecture docs, threat model v2 |
| 1 Foundation | **Partial** | Python + Go consolidated with CI; Java text fixes applied but unbuilt |
| 2 Data & contracts | **Done** | Skill contracts; knowledge SQL (verified on pgvector); `platform-api.yaml` + `agent-service.yaml` with full-coverage contract tests |
| 3 Platform backend | **Blocked** | Maven Central; local reference implementation of its contract serves clients meanwhile (ADR-0009) |
| 4 AI backend | **Partial** | Core + internal HTTP API + service-token auth verified; LangGraph/Postgres checkpointer blocked |
| 5 Skill runtime & sandbox | **Done** | §11 workflow verified in-process, over HTTP, and through the CLI |
| 6 Knowledge & RAG | **Partial** | In-process + SQL hybrid verified; LSA + stemming adopted from held-out ablation; psycopg adapter and pretrained embedder blocked |
| 7 Evaluation | **Mostly done** | Offline suites, corpus v2 with dev/test split, paired ablations, judge harness, load test; live judge run pending |
| 8 CLI & frontend | **Partial** | CLI done; web chat + history wired to the real API (client tested); npm build pending |
| 9 Reliability/security/observability | **Mostly done** | Durable single-use approvals, W3C trace propagation + JSON spans, fault injection, runbook; OTel SDK export/dashboards blocked |
| 10 Release readiness | **Partial** | Load tests, release checklist; container builds unverified (no Docker daemon) |

## Added in session 2 (all verified)

| Capability | Code | Verification |
|---|---|---|
| Public platform API contract (11 operations) | `contracts/openapi/platform-api.yaml` | `tests/contract/test_platform_api.py` validates every response; asserts every operation exercised |
| Internal agent-service contract (4 operations) | `contracts/openapi/agent-service.yaml` | `tests/contract/test_agent_api.py` (same checks) |
| Token authority: HS256 pinned, iss/aud/required claims, bounded lifetime | `ai/api/auth.py` | 6 rejected-token cases (forged, expired, wrong audience, `alg:none`, missing claims, over-long lifetime) |
| Run service: tenant-scoped runs, approve-what-you-saw (hash must match), approver permission, reject, per-run lock | `ai/api/runs.py` | contract tests (403 requester, 409 stale hash, 409 double approve, 404 cross-tenant) |
| Local platform reference implementation (refuses non-local modes) | `ai/api/platform_app.py`, `python -m ai.api platform` | contract + system tests |
| Internal agent API with service tokens | `ai/api/agent_app.py`, `python -m ai.api agent` | contract tests incl. user-token and long-lived-token rejection |
| Go CLI on the standard library (ADR-0009): `version`, `doctor`, `login` (dev user / token on stdin), `logout`, `ask`, `api search/describe`, `runs list/get/approve/reject`, `approvals`, `skills list`, `eval run`; JSON output; exit codes 0/1/2/3/4 | `apps/cli/` | `go vet`, `gofmt`, `go test -race` (3 packages, 57–63% coverage), cross-compiles linux/darwin/windows |
| CLI security: 0600 config in 0700 dir, refuses world-readable config, refuses tokens over plain HTTP to remote hosts, no redirects, response cap, escaped path params | `apps/cli/internal/{config,client}` | unit tests |
| End-to-end system test: compiled CLI → platform (uvicorn) → agent → sandbox (uvicorn) | `tests/system/test_cli_end_to_end.py` | passes; also run manually over real ports |
| Web: typed platform client, session storage, Chat page with real runs + approve/reject panel (fake reply removed), History page with status filter/approval queue + timeline | `apps/frontend/src/api/`, `pages/Chat`, `pages/History` | `tsc --strict` (against minimal shims for React/lucide), `node --test` (4 tests), Prettier check |
| Load benchmark | `evals/load.py` | measured: 338 req/s @1, 569 req/s @8, 0 errors (see evaluation README) |
| CI: Go workflow rewritten (stdlib, pinned SHAs, golangci-lint v2.14.0, govulncheck); Node-only frontend client job | `.github/workflows/` | YAML validated; golangci/govulncheck **not run locally** |

## Added in session 3 (all verified)

| Capability | Code | Verification |
|---|---|---|
| Durable SQL store for runs, single-use approvals and idempotency (ADR-0010) | `ai/storage/sql_store.py`, `ai/storage/sql/` | SQLite tests incl. 16-thread / two-connection approval race (exactly one winner) and restart durability through the runtime; every statement executed on PostgreSQL via `PREPARE` |
| Wired into both APIs (`COPILOT_STATE_DB`; required by the agent service) | `ai/bootstrap.py`, `ai/api/` | contract + system tests |
| Run listing pushed into indexed queries | `CheckpointStore.list_runs(status, limit)` | ~27 ms → ~3 ms at ~166 runs; load 421 / 1021 req/s (c=1 / c=8), 0 errors |
| Light stemmer + LSA embedder (numpy) as switchable analyzers/embedders | `ai/knowledge/text.py`, `retrieval.py` | unit tests; rank truncation bug found and fixed during evaluation |
| Corpus v2 (120 docs) + dev/test retrieval and selection sets, deterministic generator | `evals/corpora/`, `evals/datasets/v2/` | regenerated output byte-identical |
| Paired ablation runner (bootstrap CIs, wins/losses) | `evals/ablation.py`, `evals/metrics.py` | held-out: LSA + stem ΔMRR +0.240 [+0.13, +0.36]; adopted for docs; no v1 agent flips |
| LLM-judge harness: versioned rubric, calibration set, κ agreement, consistency, cost; opt-in Anthropic provider | `evals/judge.py`, `ai/models/anthropic.py` | harness + request-shape tests; live call **not run** (no key) |
| W3C trace context: API → agent/skill spans → gateway, JSON span export | `ai/telemetry.py`, `ai/api/http.py`, `skills/api/gateway.py` | end-to-end propagation test |
| Runbook and release checklist | `docs/operations/` | reviewed against code |

## Commands actually executed (final state, 2026-10-04)

| Command | Result |
|---|---|
| `pytest` with `COPILOT_TEST_PGURL` | **150 passed** (unit, integration, contract, pgvector + runtime SQL on PostgreSQL, CLI system test) |
| `pytest` (no database) | 143 passed, 7 skipped |
| `ruff check` / `ruff format --check` | clean |
| `mypy` (strict, 83 files) | no issues |
| `python -m evals run --suite smoke` / `full` | exit 0; task success 0.846 (n=13) / 0.763 [0.632, 0.895] (n=38); 0 safety violations |
| `go vet`, `gofmt -l`, `go test -race ./...` | clean; 3 packages ok |
| `node --test src/api/client.nodetest.ts`; `tsc --strict` on changed web files | 4 passed; no type errors |
| `python -m evals.load` (c=1, c=8) | 0 errors |
| `python -m evals.ablation --split dev/test`; `python -m evals.judge calibrate` | exit 0 |
| `mvn verify`, `npm ci`, Docker builds | not runnable (registries / no daemon) |

## Security findings and remaining risks

New controls this session: T16 (service-to-service auth), T18 (approve exactly what was
shown), T19 (client token handling), T20 (request limits) — see `docs/security/threat-model.md`.

Remaining:
- Local PDP is a dev stand-in; the durable store is SQLite (single node) until the PostgreSQL driver is available.
- Service tokens use a shared HS256 secret (production: asymmetric keys or mTLS).
- DNS-rebinding window in outbound HTTP (mitigate with network egress policy).
- Spring Boot 3.3.2 (EOL) and the Spring AI milestone remain in `pom.xml`.
- Dashboard page still shows placeholder "—" stats (labelled as not connected, no fake numbers).
- Web app XSS hardening/CSP review pending its first real build.

## Deferred work and dependencies

| Item | Depends on |
|---|---|
| `uv.lock`, `package-lock.json`, Maven wrapper | registry access |
| psycopg connection factory for `SqlRuntimeStore`; LangGraph adapter + Postgres checkpointer | PyPI |
| psycopg `Retriever`; semantic embedder | PyPI (+ model host) |
| Spring Boot 4.1 implementation of `platform-api.yaml`, run against `tests/contract/` | Maven Central |
| Web: npm build, Vitest component + a11y tests, eval dashboard, real dashboard metrics | npm |
| Live judge calibration run, independently labelled calibration items, more API-selection data | API key / second annotator |
| OTel SDK exporter, collector + Grafana dashboards, container build verification | PyPI / Docker daemon |
| GitHub integration skill | concrete use case |

## Exact next step

With registries reachable: `uv lock && uv sync --extra dev --extra orchestration --extra postgres`;
add a psycopg connection factory for `SqlRuntimeStore` using the `POSTGRES` dialect (schema
and statements already verified) and run the store tests against it; then the LangGraph
adapter with `langgraph-checkpoint-postgres`; then the Spring Boot 4.1 implementation of
`platform-api.yaml` against `tests/contract/`.
