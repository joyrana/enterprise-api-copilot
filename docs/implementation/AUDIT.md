# Repository Audit and Baseline

- **Audit date:** 2026-10-03
- **Base commit:** `2e5ef5b` ("fixes and adjustments"), 2 commits total, clean working tree before this session
- **Auditor:** implementation session 1 (see `STATUS.md`)

This document records what the repository actually contained and what actually ran
before any changes were made. Everything below was observed, not assumed.

## 1. Execution environment for this audit

| Item | Observed |
|---|---|
| OS | Linux (x86_64), 2 vCPU, ~7 GiB RAM |
| Python | 3.13.16 (repository targets 3.12) |
| Java / Maven | OpenJDK 21.0.12, Maven 3.9.11 (no `mvnw` in repo) |
| Go | 1.24.7 (repository targets 1.22) |
| Node | 22.22.0 (repository CI targets 20) |
| PostgreSQL | 16.15 local cluster; **pgvector 0.8.7 built from source** for this audit |
| Docker | CLI present, **no daemon** — Compose and image builds cannot run |
| Package registries | **Blocked by egress policy:** Maven Central (`repo.maven.apache.org`, `repo1.maven.org`), PyPI, npm registry, `proxy.golang.org` all return 403 "host not in allowlist". GitHub git reads work. |

The registry block is an external constraint of this session, not a repository
defect. It determines which components could be built (see §3).

## 2. Inventory: documented vs. actual

| Area | README / docs claim | Actual state at `2e5ef5b` |
|---|---|---|
| Python AI runtime (`ai/`) | Supervisor, planner, memory, reflection runtime | Placeholder nodes. Supervisor hard-codes `intent = "api_execution"`; planner always returns the same 4-step plan; memory nodes return `{}`. No graph is assembled anywhere — no `StateGraph`, no entry point, no HTTP service. |
| `agents/` | "Legacy compatibility shims" | Re-export shims of `ai/`. No callers other than `Makefile`/CI test paths. |
| Skills | "Stateless MCP tools" | `skills/api/discovery` returns one hard-coded result; `skills/jwt` returns `PLACEHOLDER_TOKEN_NOT_IMPLEMENTED`; `skills/docs` and `skills/github` raise `NotImplementedError`. Hyphenated legacy dirs (`api-discovery`, `api-executor`, `sdk-generator`, `documentation`) are not importable as packages. |
| MCP | MCP tool servers | All skill servers **fail to import** against the current MCP Python SDK (2.x): `AttributeError: 'Server' object has no attribute 'list_tools'` (v1 low-level decorator API was removed). `mcp` is also missing from `requirements.txt`. |
| Spring Boot backend | Control plane: auth, registry, runs, audit | One `GET /api/v1/health` endpoint, exception handler, security config (JWT resource server commented out, so every non-public route returns 401/403 with no way to authenticate), Flyway V1 schema with 4 tables and no code using them. |
| Go CLI | `ask`, `api`, `login`, `doctor` | All commands print "not yet implemented"; `doctor` only checks `/api/v1/health`. |
| Frontend | Chat, history, dashboard | Static pages. **Chat returns a fabricated assistant reply after a `setTimeout`** (fake success state). Dashboard stats are hard-coded `—`. |
| Vector store | "pgvector / Qdrant" | No vector code; Qdrant appears in `.env.example`, docs and Helm notes only. |
| Observability | "OpenTelemetry at every layer" | Spring dependencies only. No Python instrumentation; `observability/` contains READMEs only; Compose mounts a non-existent `docker/observability/prometheus.yml`. |
| Contracts | `contracts/openapi`, `asyncapi`, `json-schema` | READMEs only. |
| SDKs (`sdk/*`) | Java/Python/TS/Go SDKs | READMEs only. |
| Apigee (`apigee/`) | Proxy configuration and policies | README only. |
| Tests | Unit/integration across components | Python: **0 tests**. Go: 3 tests (depend on `testify`, which is not in `go.mod`). Java: 1 `@SpringBootTest` IT requiring a live PostgreSQL. Frontend: 0 tests. |

## 3. Baseline build/test results (before any change)

| Component | Command | Result |
|---|---|---|
| Python lint | `ruff check ai/ skills/ agents/` | 2 errors (E501, UP042); config uses deprecated top-level ruff keys and removed rules `ANN101/ANN102`. |
| Python tests | `pytest ai skills agents` | **0 tests collected.** |
| Python imports | `import ai.supervisor.agent` etc. | Fails: `langchain_core` not installable here; skill modules fail on MCP 2.x API (see §2). |
| Go | `go build ./...` | **Fails:** no `go.sum`; `testify` used by tests but absent from `go.mod`. Dependency download additionally blocked in this session. |
| Java | `mvn verify` | **Not runnable here** (Maven Central blocked). Independent defects that would fail CI anyway: no `mvnw` (Makefile, Dockerfile and CI call `./mvnw`); `checkstyle/suppressions.xml` referenced but missing; JaCoCo gate at 80% line coverage with one smoke test; `spring-milestones` repository required for Spring AI `1.0.0-M1`; IT needs a running PostgreSQL but no Testcontainers wiring. |
| Frontend | `npm ci && npm run build` | **Not runnable here** (npm blocked). Independent defect: no `package-lock.json`, so `npm ci` in CI and in `Dockerfile.frontend` fails. |
| Docker | `docker compose build` | Not runnable (no daemon). Independent defects: `Dockerfile.backend` copies non-existent `mvnw` and `.mvn/`; `Dockerfile.cli` copies non-existent `go.sum`; Compose references `agent-service` that is not defined. |

## 4. Defects and risks found

### Correctness / build
1. Go module path was `github.com/your-org/enterprise-api-copilot/cli` (placeholder org); build `-ldflags -X main.version` targets `main`, but the variables live in package `commands`, so injected versions never apply.
2. `ai/requirements.txt` is `-r ../agents/requirements.txt`; all ranges are unpinned lower bounds; no lockfile anywhere in the repo.
3. `pyproject.toml` `testpaths`/`addopts` force `--cov` (pytest-cov not installed → pytest errors when coverage plugin missing).
4. `skills/api/sdk_generator`: generated Java leaves `entity` unassigned when there is no body (does not compile); generated Python mis-indents the `json=` argument; header values (including `Authorization`) are copied verbatim into snippets.
5. Reflection routing can only return `executor`/`end`; the planner route is declared but unreachable.

### Security
1. **SSRF / excessive agency:** `skills/api/executor` performs arbitrary `httpx` requests to any URL with any headers, follows no allowlist, has no response size limit, and returns all response headers. Any model-produced URL (including cloud metadata endpoints) would be fetched.
2. No authorization, approval, idempotency or audit on any side-effecting skill.
3. Exceptions are stringified into tool results (`str(e)`), which can leak internals.
4. Hard-coded shared passwords in Compose (`changeme` for Postgres/Redis, `admin` for Grafana), published on all interfaces.
5. `.env.example` uses `sk-...` and `changeme-use-a-256-bit-random-string` placeholders that look like credentials; `APIGEE_BASE_URL` defaults to the Apigee **management** API (`apigee.googleapis.com`), conflating management plane and runtime proxy invocation.
6. Spring `SecurityConfig`: CORS `allowCredentials(true)` with header wildcard; resource server disabled, so no endpoint can be legitimately authorized.
7. Nginx CSP allows `http: https: 'unsafe-inline'` — effectively no script restriction.
8. CI uses floating `aquasecurity/trivy-action@master` and `golangci-lint version: latest`; `docker-build.yml` grants `security-events: write` to PR builds.

### Architecture contradictions
1. Two Python trees (`ai/`, `agents/`) and two skill layouts (grouped vs. hyphenated).
2. README says "Backend → Supervisor" but there is no agent service, no contract between Spring and Python, and Compose references an undefined `agent-service`.
3. Spring AI + OpenAI starter in the Java backend duplicates the Python model layer; the LLM provider would be configured in two places.
4. Qdrant listed as a vector store alongside pgvector; Redis is wired into the backend with no use.
5. EOL dependencies: Spring Boot 3.3.x reached end of OSS support on 2025-06-30; Spring AI pinned to a pre-GA milestone.

## 5. What was preserved

- Java hexagonal package layout, error contract (`ApiErrorResponse`), Flyway baseline and health endpoint.
- CLI command tree and UX (`version`, `doctor`, `ask`, `api`, `login`).
- Frontend layout and routing.
- `ai/shared/state.py` concepts (execution status, steps) — carried into typed contracts.
- SDK snippet generation idea (rewritten for correctness and secret-safety).
- Existing ADR-0001..0004 (superseded only where explicitly stated in ADR-0005..0008).
