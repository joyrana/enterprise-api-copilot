# Master Implementation Plan

Companion documents: [`AUDIT.md`](AUDIT.md) (baseline), [`STATUS.md`](STATUS.md) (live status).

Each phase is a vertical slice that leaves the repository buildable. "Done" means the
acceptance criteria are demonstrated by tests or reproducible commands — see the
Definition of Done in §3.

## 1. Phases

| # | Phase | Depends on | Acceptance criteria (executable) | Status |
|---|---|---|---|---|
| 0 | Audit and baseline | — | `AUDIT.md` lists observed build/test results; ADRs 0005–0008 resolve the layout, authority, data and evaluation contradictions | **Done** |
| 1 | Foundation hardening | 0 | One canonical Python tree; `ruff check` and `pytest` green; Python CI runs lint + tests + smoke eval without credentials; no `your-org` URLs; no shared hard-coded passwords in Compose; Java/Go/frontend build defects fixed | **Partial** — Python done and verified; Java/Go text fixes applied (Checkstyle suppressions, no `mvnw`, module path, ldflags, testify) but unbuilt; frontend untouched (registries blocked) |
| 2 | Data and contracts | 1 | Knowledge schema migration applies on PostgreSQL+pgvector; skill contracts produce JSON Schema; synthetic OpenAPI spec + sandbox gateway run locally; platform REST contract published | **Done** — platform + agent-service OpenAPI contracts with contract tests covering every operation |
| 3 | Platform backend | 1, 2 | Spring Boot on a supported line; API catalog, skill registry, runs, approvals, audit endpoints with Flyway migrations, Testcontainers ITs, authorization tests | **Blocked** — Maven Central unreachable |
| 4 | AI backend | 2 | Typed intent → plan → bounded execution with budgets and recovery; LangGraph adapter with checkpointing; documented HTTP API; service-to-service auth with platform | **Partial** — core + internal HTTP API + service-token auth done; LangGraph adapter and Postgres checkpointer blocked (PyPI) |
| 5 | Skill runtime and sandbox | 2 | Skills with full contracts; PEP + approvals + idempotency + audit; SSRF-safe gateway adapter; MCP adapter with no bypass; end-to-end sandbox workflow test | **Done** for discovery, describe, execute, SDK, JWT, docs; GitHub deferred |
| 6 | Knowledge and RAG | 2 | Ingestion with stable IDs and versions; BM25, dense, hybrid (RRF); tenant filtering; context budgets; grounded answers with citations; abstention; retrieval benchmark and ablation | **Partial** — in-process + SQL hybrid verified; 120-doc corpus with held-out ablation chose LSA + stemming; psycopg adapter and pretrained embedder blocked |
| 7 | Evaluation platform | 5, 6 | Versioned datasets for all required categories; deterministic evaluators; runner with provenance; JSON+MD reports; safety hard gates; baseline + ablation measured | **Mostly done** — suites, dev/test split, paired ablations, judge harness with calibration/agreement/consistency; live judge run pending (opt-in key) |
| 8 | CLI and frontend | 3, 4 | Real endpoints; no fabricated states; run history, approvals, eval views | **Partial** — CLI done (stdlib, tested end to end); web chat/history wired to the API, fake reply removed; npm build, component tests and eval dashboard blocked (npm) |
| 9 | Reliability, security, observability | 4, 5 | OTel traces end-to-end; failure injection; authz regression tests; runbooks | **Mostly done** — W3C trace propagation API→agent→gateway with JSON span export, durable single-use approvals, fault injection, runbook; OTel SDK exporter + dashboards blocked (PyPI) |
| 10 | Performance and release readiness | all | Load tests, container builds, deployment manifests, release checklist | **Partial** — load tests (file vs SQL store), release checklist; container builds unverified (no Docker daemon) |

## 2. Ordered next steps

1. **Unblock registries** (PyPI, npm, Maven Central) in the execution environment.
2. Lockfiles: `uv lock`, `npm install` → `package-lock.json`, Maven wrapper (the CLI needs none).
3. Phase 4: psycopg connection factory for `SqlRuntimeStore` (`POSTGRES` dialect, schema already verified); LangGraph adapter over `ai/agent/orchestrator.py` with the Postgres checkpointer.
4. Phase 6: psycopg `Retriever` over the `knowledge` schema; semantic embedder behind `Embedder`; re-run paired RAG/selection evaluation.
5. Phase 3: Spring Boot 4.1 migration; implement `contracts/openapi/platform-api.yaml` (runs, approvals, catalog, skills) and run `tests/contract/` against it; mint service tokens for the agent; then retire the local facade.
6. Phase 8: `npm install`, run Vitest/ESLint/build, add component + accessibility tests, eval dashboard.

## 3. Definition of Done (per feature)

Behaviour implemented (not described) · typed contracts · unit + integration tests ·
authorization and failure paths tested · telemetry without sensitive data · docs match
code · CI green · benchmark claims reproducible · limitations recorded · no unexplained
TODOs on the critical path.
