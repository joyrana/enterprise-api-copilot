# Technology Baseline

- **Research date:** 2026-10-03
- **Method:** release tags read directly from upstream Git repositories (`git ls-remote --tags`), vendor release notes and end-of-life trackers. PyPI and the npm registry were not reachable from the research environment, so PyPI/npm "latest" values below come from upstream tags, not registry metadata.
- **Rule:** stable releases only; previews must be justified explicitly. "Latest" is a research input, not an instruction to upgrade blindly.

## Selected versions

| Area | Current upstream (2026-10-03) | Repository before | Selected target | Status in repo |
|---|---|---|---|---|
| Python | 3.13 (3.12 still supported) | 3.12 | `>=3.12,<3.14`; CI on 3.12 and 3.13 | Applied (`pyproject.toml`) |
| LangGraph | 1.2.12 (1.x line, Sep 2026) | `>=0.2.0` | `langgraph>=1.2,<2` | Declared; **not installed** (PyPI blocked) — orchestration adapter deferred |
| langchain-core | 1.6.6 | `>=0.2.0` (via `langchain`) | only if LangGraph requires it; no `langchain` meta-package | Declared as LangGraph transitive only |
| Pydantic | 2.13.x stable (2.14 in beta) | `>=2.8` | `pydantic>=2.13,<3` | Applied, installed 2.13.5 |
| MCP Python SDK | 2.3.0 (2.x GA; targets protocol revision 2026-07-28, backward compatible with 2025 revisions) | `mcp` missing; code used v1 API | `mcp>=2.2,<3` | Applied; tested with installed 2.2.0 |
| HTTP server (agent API) | FastAPI 0.142.x / Starlette 1.6 | FastAPI `>=0.112` | Starlette now (sandbox only); FastAPI for the agent API when installable | Sandbox uses Starlette 1.6 |
| HTTP client | httpx 0.28.1 | `>=0.27` | `httpx>=0.28,<0.29` | Applied |
| PostgreSQL | 18.x (REL_18_6); 17 and 16 supported | 16 (`pgvector/pgvector:pg16`) | **17** for Compose (supported until 2029, mature pgvector images); code is tested against 16 locally | Compose updated |
| pgvector | 0.8.7 | unspecified (image tag `pg16`) | `0.8.x`, image `pgvector/pgvector:0.8.1-pg17` or newer | Local tests ran on 0.8.7 |
| Postgres driver (Python) | psycopg 3.3.6 | none | `psycopg[binary]>=3.3,<4` | Declared; **not installed** — DB adapter deferred; SQL validated via `psql` |
| Redis | 8.x | 7 (wired, unused) | Not used by any feature. Deferred until a measured need (ADR-0007) | Still in Compose because the current backend build includes `spring-boot-starter-data-redis`; removed with the Phase 3 backend migration |
| Java | 21 LTS (25 LTS also available) | 21 | 21 (prompt requirement) | Unchanged |
| Spring Boot | **4.1.1** supported until 2027-07-31; 4.0.x until 2026-12-31; **3.3.x EOL since 2025-06-30** | 3.3.2 | 4.1.x — requires a deliberate migration (Jackson 3, Spring Framework 7) | **Deferred** — Maven Central blocked, migration cannot be verified here |
| Spring AI | 2.x (Boot 4 line) | 1.0.0-M1 milestone | **Remove** from backend (model calls live in Python; ADR-0005) | Planned, not yet applied (unverifiable) |
| Go | 1.27.1 | 1.22 (EOL) | 1.26+ minimum, CI on stable | Planned (cannot fetch modules here) |
| Cobra | 1.10.2 | 1.8.1 | 1.10.x | Planned |
| React | 19.3.0 | 18.3 | 19.x after test harness exists | Planned |
| TypeScript | 7.0 (new native compiler) | 5.5 | stay on 5.x/6.x until Vite/ESLint toolchain support for 7 is verified | Planned |
| Vite | 8.3.x | 5.3 | 8.x | Planned |
| OpenTelemetry Python | 1.45.0 | `>=1.26` | `opentelemetry-sdk>=1.44,<2` | Declared; API 1.44 installed |
| OTel semantic conventions | 1.44.0; **GenAI conventions are all `development` stability** (moved to `open-telemetry/semantic-conventions-genai`) | n/a | Use `gen_ai.*` names (`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.tool.name`) behind one module so renames are a one-file change | Applied in `ai/telemetry.py` |
| Anthropic / OpenAI SDKs | anthropic-sdk-python 1.11.0; openai-python 3.24.0 | `openai>=1.40` | Optional extras behind the `ModelProvider` interface; default provider is deterministic/offline | Interface applied; vendor adapters deferred |
| Ruff | 0.16.x | `>=0.5` | `ruff>=0.16` | Applied (0.16.8) |
| Pytest | 9.1.x | `>=8.3` | `pytest>=9` | Applied (9.1.1) |

## Evaluation frameworks

RAGAS, DeepEval and similar frameworks were considered. They are **deferred**: the
core metrics this project needs (Recall@k, Precision@k, MRR, nDCG, tool-selection
P/R/F1, authorization outcomes, citation validity, secret leakage) are deterministic
and are implemented directly in `evals/` with unit tests. Adding a framework would
add a dependency without adding a capability. An LLM-judge adapter will be added only
for semantic answer-quality metrics, with versioned rubrics and calibration (see
`docs/evaluation/README.md`).

## Deferred technologies

| Technology | Reason |
|---|---|
| Qdrant | pgvector covers dense retrieval at current scale; a second vector store doubles operational surface with no measured benefit. |
| Kafka | No asynchronous workload yet; a transactional outbox in PostgreSQL is sufficient initially. |
| Redis | No caching or coordination need has been measured. Re-evaluate for rate-limit counters across replicas. |
| Graph database | Relationship queries (API → schema → scope → proxy) fit relational tables until benchmarks say otherwise. |
| Spring AI | Model access belongs to the Python AI service. |
| LangSmith | Hosted observability must not be required for development; OTel + local stack instead. |

## Sources

- LangGraph releases: https://releasebot.io/updates/langchain-ai/langgraph
- Spring Boot support lines: https://isitpatched.com/eol/spring-boot ; https://spring.io/blog/2026/06/10/spring-boot-4-0-7-available-now/
- MCP Python SDK v2.0.0 release notes: https://newreleases.io/project/github/modelcontextprotocol/python-sdk/release/v2.0.0
- pgvector release notes: https://www.enterprisedb.com/docs/pg_extensions/pgvector/rel_notes/
- GenAI semantic conventions: https://github.com/open-telemetry/semantic-conventions-genai (stability read from `model/**/*.yaml`)
- Upstream tags (git): golang/go, spf13/cobra, facebook/react, microsoft/TypeScript, vitejs/vite, fastapi/fastapi, pydantic/pydantic, postgres/postgres, pgvector/pgvector, psycopg/psycopg, open-telemetry/opentelemetry-python, anthropics/anthropic-sdk-python, openai/openai-python, modelcontextprotocol/python-sdk, astral-sh/ruff, langchain-ai/langchain.
