# Implementation Status

- **Last updated:** 2026-11-24 (session 4: LLM-agent production gaps G1–G15)
- **Plan:** [`MASTER_PLAN.md`](MASTER_PLAN.md) · **Baseline audit:** [`AUDIT.md`](AUDIT.md) · **Decisions:** ADR-0011 (LLM-driven agent), ADR-0012 (Spring platform)

## Environment

Session 4 had working PyPI, npm and Maven Central access, Java 21, Go, PostgreSQL 18 (local, no
Docker daemon) and an Apple-Silicon mlx-lm server with `Qwen3-4B-Instruct-2507-4bit`, so the
earlier "registry blocked" caveats below apply to sessions 1–3 only. Still **not** done: no
GitHub Actions run (so the new workflows are unexecuted), no Docker image builds, no real OIDC
identity provider, no PostgreSQL run of the agent's `SqlRuntimeStore` tests
(`COPILOT_TEST_PGURL` unset; the new conversation tables' PostgreSQL twin is therefore
syntax-reviewed only).

## PR review (session 5)

The three stacked PRs were reviewed and run end to end locally (Python facade and Spring
jar contract suites, PostgreSQL 18 integration tests, Go CLI system tests, Vitest + Node
tests, the live stack against mlx-lm, and a live `agent_llm` re-record). Findings, all fixed:

| # | Severity | Finding | Fix | Evidence |
|---|---|---|---|---|
| R1 | **Security** | A viewer could answer another user's clarification with their own values; the run kept the requester's permissions and paused for approval of that amount (confused deputy). Colleagues could read and post into another user's conversation | `clarify` is requester-only (403); conversations are private to their creator (404) | Reproduced through the API before the fix; contract `test_conversations_and_clarification` on both implementations; History only offers the answer box to the requester |
| R2 | High | The approval summary showed the path template (`/v1/payments/{payment_id}/refunds`), so an approver could not see *which* payment | Summary shows the concrete path and query | `test_undescribed_calls_…` |
| R3 | High | The run time budget used the wall clock: a sleep/wake or NTP step failed healthy runs with "run deadline exceeded" (found when a live eval ran across a sleep: 6 runs failed after 8–39 s) | Budget measured on a monotonic clock per segment | `test_a_wall_clock_jump_does_not_exhaust_the_run_budget` |
| R4 | High | The reply could state identifiers no step produced (`pay_12345`, an invented request example) | Reply identifiers/operation names must appear in the run's evidence: one corrective retry, then `[unverified]` | `test_invented_identifiers_in_the_reply_are_retried_then_masked` |
| R5 | Medium | `npm run test:node` (a CI job) failed: `client.ts` imported `./sse` without an extension | `./sse.ts` | `node --test` 4/4 |
| R6 | Medium | The 4B model proposed calls before describing them; rejections withdrew the skill and multi-step tasks (G3) dead-ended | Orchestrator runs the needed `api.describe` (read-only), then validates the call | live: "Refund the latest captured payment for ₹100" now pauses for approval naming the id and its provenance |
| R7 | Medium | Invalid component choices (source named by operation id) left the reply with no components | Map operation id → step; fall back to the default layout of real data | `test_invalid_component_choices_fall_back_to_real_data` |
| R8 | Medium | `token.inspect` rejected a token whose signature segment was corrupt (PyJWT refuses it even unverified), and the planner retried the identical failing call four times | Header/claims still decoded with the corruption reported; identical failed calls are refused | `test_jwt_with_a_corrupted_signature_is_still_inspected`, `test_an_identical_call_that_already_failed_is_not_retried` |
| R9 | Low | Unusable planner output after real progress failed the whole run | Planning stops and the model answers from what it has (`plan_unusable`); before any progress, and for an unreachable model, the run still fails | two `test_unusable_planner_output_…` tests |
| R11 | High | Live: after an approved refund executed (HTTP 200), the run ended FAILED "tool-call budget exhausted", which hides the write and invites a duplicate retry; an approved step could also be refused because its paused attempt had already used the last tool call. The orchestrator's own describes also used up the model's step budget | Budgets reached after progress end planning and answer (`budget_reached`); an approved step runs; orchestrator steps count only against the tool-call budget | `test_a_write_that_uses_the_last_tool_call_still_completes`, `test_orchestrator_describes_do_not_use_the_models_step_budget`; live: refund → approval → HTTP 201 → COMPLETED |
| R10 | Low | "Get payment <id>" flipped between execution and discovery on the 4B model | `intent-v4`: id-bearing get/show/fetch is execution (examples do not reuse eval wording) | live intent accuracy 0.917 → 0.944 |

Live end to end on the local stack (platform → agent → mlx-lm): 15/16 checks then G3 after
R11 — "Refund the latest captured payment for ₹100" paused with the concrete target and the id's
provenance, was approved by an approver and created the refund (HTTP 201, COMPLETED). Viewer
clarify → 403, colleague's conversation → 404, self-approval → 403, replay → 409, three
concurrent runs completed. A run that spanned a 30-minute laptop sleep completed with
`elapsed_s` 15 s (R3 working).

Live `agent_llm` after the fixes ([report](../evaluation/agent_llm_review_live_report.md)):
status and argument accuracy 1.0, intent 0.944, skill F1 0.915, model calls/run 5.14 → 4.75,
repair rate 0.028 → 0, p95 31.5 s, safety violations 0; the replay baseline was rewritten from
these recordings. **Open:** on `adv-008` ("every payment for the globex tenant") the 4B model
still words the caller's own payments as globex's despite the responder rule (no data
crosses tenants). pgvector is not installed locally, so its 4 SQL tests were not run.

## LLM-agent gaps (session 4)

Branches: the work landed on `feat/agent-p0-security-correctness` (Phase 0),
`feat/agent-p1-conversations` (Phase 1) and `feat/agent-p2-p5-observability-capacity-ui`
(Phases 2–7; mixed in two commits because the changes share files). Nothing is pushed or merged.

| Gap | Status | Evidence | Not done / caveat |
|---|---|---|---|
| G8 secrets to the model | **Done** | `sanitize_request` in `generate_structured` (every stage, every retry); `tests/unit/test_llm_secrets.py`; eval cases `adv-004` | Pattern-based; unknown credential shapes can pass |
| G9 failure after a write | **Done** | `summary_unavailable`, COMPLETED vs FAILED tests (responder and planner) | — |
| ADR-0011 | **Done** | `docs/adr/ADR-0011.md` | — |
| G1 conversation memory | **Done** | SQL-backed (`V002`), tenant-scoped; scripted tests incl. "curl for it" and ₹200→₹150; **live**: "show me the curl for it" → `refundPayment`, and eval case `l-028` (₹150, payment id from the earlier turn) passes on the real model | — (the PostgreSQL twin of V002 is executed by `test_conversation_statements_are_tenant_scoped`) |
| G2 resumable clarification | **Done** | `POST /runs/{id}/clarify` + plain next message routed; live: "Create a payment for cust_acm0001" → "₹500" → approval → HTTP 201, no model call to resume | The intent-level "too vague" clarification is not resumable (a new message in the conversation covers it) |
| G3 grounding from API results | **Done** | provenance in the event and approval summary; docs/failed calls never sources (`test_conversations`); the orchestrator now runs the `api.describe` a proposed call needs instead of rejecting it, which is what stopped the 4B model; `test_llm_agent::test_undescribed_calls_are_described_first_and_ids_come_from_results` | Live result in the review section below |
| G7 model observability | **Done** | `llm.generate` spans, `model_call` events with prompt versions, opt-in payload capture; `test_llm_tracing.py` | — |
| G5 LLM evaluation | **Done** | `python -m evals agent-llm`, 36 cases / 8 adversarial, recordings + baselines in `docs/evaluation/` | Replay measures the code around the model, not the model; the committed live report predates one case's re-record (`l-027`) |
| G15 CI with a real model | **Written, never run** | `.github/workflows/evals-live.yml` (macOS arm64, nightly + dispatch), replay step in `python-ci.yml` | Needs a push to verify; the `mlx-lm==0.29.1` pin and runner label are untested |
| G4 async, SSE, concurrency | **Done** | 202 + SSE (resumable), tenant-fair limiter, 429 + `Retry-After`, queue wait recorded and excluded from the budget; **live** through the Vite proxy: two concurrent runs both completed, one with 6.5 s queue wait | The React live-steps view is covered by unit tests only (no browser session). Found and fixed by the live run: the stream closed when the status turned COMPLETED, before the reply existed; `RunState.settled` now gates it (regression test with a held-back responder) |
| G6 fewer wasted calls | **Done, measured** | probe for `response_format`, robust JSON extraction, skill withdrawal after two rejections, hints: model calls/run 5.61 → 5.14, rejected-decision rate 0.29 → 0.20, skill F1 0.88 → 0.93, intent accuracy unchanged | mlx-lm 0.29.1 does not honour `response_format` (probe says so), so no constrained decoding |
| G10 skills declare intents | **Done** | resolver built from the registry; legacy table frozen as an oracle in `test_resolver.py`; start-up validation | Skill order in prompts is now `SkillDefinition.order`, not per-intent |
| G12 one component registry | **Done** | `contracts/json-schema/ui-components.json`, server-side props validation; Python and Vitest drift tests | — |
| G11 every client renders UI | **Done** | History page renders `GenUI` (approve only for approvers on pending runs); Go CLI renders every component, `--json`; system test covers discovery, write + approval, clarification resume | — |
| G14 Spring Boot platform | **Done** | `mvn verify` green (Spotless, Checkstyle, 27 tests, JaCoCo ≥ 80 %); `tests/contract` passes against the Python facade **and** the Spring jar with PostgreSQL | Spring Boot 3.5 (not 4.x); OIDC unverified. Verified on the full live stack (`./dev.sh --with-backend`: mlx-lm, sandbox, agent, Spring, local PostgreSQL, Vite): async runs + SSE through the proxy, conversation, clarification, approval 403 for a developer / 200 for an approver, a payment created in the sandbox, approval decisions and audit rows in PostgreSQL, and the Go CLI rendering components against it |
| G13 documentation | **Done** | principles, overview, threat model (T22–T29), runbook, README, ADR-0011/0012, this file | — |

### Measured on the real model (36 cases, Qwen3 4B, mlx-lm 0.29.1)

| | Phase 2 baseline | After G6 |
|---|---|---|
| Intent accuracy | 0.917 | 0.917 |
| Skill precision / recall / F1 | 0.83 / 0.93 / 0.88 | 0.93 / 0.93 / 0.93 |
| Argument exact match | 1.0 (n = 13) | 1.0 (n = 13) |
| Model calls per run | 5.61 | 5.14 |
| Rejected-decision rate | 0.29 | 0.20 |
| Latency p50 / p95 | 16.6 s / 36.5 s | 16.9 s / 37.4 s |
| Safety violations | 0 | 0 |

Latency is wall clock on one machine while other work ran; treat differences under ~10 % as noise.
The prompts changed between the columns, so the second column's recordings are the committed ones.

### Decisions that differ from, or add to, the prompt

- One intermediate bug found by running live and fixed: the event stream closed when the status
  turned COMPLETED, before the reply and UI existed; runs now end with a `settled` event and the
  stream waits for it. A second: `input_tokens`/`output_tokens` in `model_call` events were being
  redacted as credentials; they are `usage_in`/`usage_out` now.
- Intent entities from the model now read `"null"`/`null` for empty lists as empty (a live
  multi-turn case failed twice on this); values are still grounded afterwards.
- The Spring backend drops Redis, JPA, Spring AI and the unused scaffold schema (never deployed).
- Skills carry an `order` next to `intents` so the planner sees them in a stable, sensible order.

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| 0 Audit & baseline | **Done** | `AUDIT.md`, ADR-0005…0009, architecture docs, threat model v2 |
| 1 Foundation | **Partial** | Python + Go consolidated with CI; Java text fixes applied but unbuilt |
| 2 Data & contracts | **Done** | Skill contracts; knowledge SQL (verified on pgvector); `platform-api.yaml` + `agent-service.yaml` with full-coverage contract tests |
| 3 Platform backend | **Done (session 4)** | Spring Boot implementation of `platform-api.yaml` (ADR-0012); contract suite passes on it and on the Python facade |
| 4 AI backend | **Partial** | LLM-driven core + internal HTTP API (runs, SSE, conversations, catalog) + service-token auth verified; LangGraph/Postgres checkpointer not built |
| 5 Skill runtime & sandbox | **Done** | §11 workflow verified in-process, over HTTP, and through the CLI |
| 6 Knowledge & RAG | **Partial** | In-process + SQL hybrid verified; LSA + stemming adopted from held-out ablation; psycopg adapter and pretrained embedder blocked |
| 7 Evaluation | **Mostly done** | Offline suites, corpus v2 with dev/test split, paired ablations, judge harness, load test; live judge run pending |
| 8 CLI & frontend | **Done (session 4)** | CLI renders UI components; web chat streams progress, History renders GenUI; lint, type-check, 18 Vitest tests, build pass |
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

## Commands actually executed (session 4, 2026-11-24)

| Command | Result |
|---|---|
| `ruff check .`, `ruff format --check .`, `mypy` | clean (strict, 103 files) |
| `pytest -q` | **239 passed, 7 skipped** (the skips need `COPILOT_TEST_PGURL`); includes the contract suite against the Spring jar. With `COPILOT_TEST_PGURL` set to a local PostgreSQL: 243 passed, 4 errors (the pgvector tests; no extension installed) |
| `python -m evals agent-llm --replay --baseline docs/evaluation/agent_llm_baseline_phase2.json` | exit 0, 0 safety violations |
| `python -m evals agent-llm --live --record` (twice: Phase 2 code, then Phase 3 code) | 36 cases each; 0 safety violations; `l-027` re-recorded alone afterwards |
| `npm run lint`, `type-check`, `test`, `format:check`, `build` (apps/frontend) | all pass (18 tests) |
| `go vet ./...`, `gofmt -l`, `go test ./...` (apps/cli) | clean |
| `mvn -B verify` (apps/backend, JDK 21) | BUILD SUCCESS (27 tests, coverage gate met) |
| Live: platform + sandbox + mlx-lm, memory / clarify / async-SSE scenarios | see the gap table; two concurrent runs via the Vite proxy both completed |
| `./dev.sh --with-backend`, then scripted requests through `localhost:3000` and the compiled CLI | works end to end on the real model (see the gap table) |
| Not run | GitHub Actions workflows, Docker builds, pgvector tests, a browser walkthrough |

## Security findings and remaining risks

New controls this session: T16 (service-to-service auth), T18 (approve exactly what was
shown), T19 (client token handling), T20 (request limits) — see `docs/security/threat-model.md`.

Remaining:
- Local PDP is a dev stand-in; the durable store is SQLite (single node) until the PostgreSQL driver is available.
- Service tokens use a shared HS256 secret (production: asymmetric keys or mTLS).
- DNS-rebinding window in outbound HTTP (mitigate with network egress policy).
- Spring Boot 3.5.16 is past OSS support; Boot 4.x is the supported line (follow-up).
- The model queue limiter is per process; the shared HMAC keys between Spring and the agent are the weakest link between them.
- G3 live demonstration and the G15 workflows are open (see the gap table).
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

Push the branches and let `python-ci.yml` (replay) and `evals-live.yml` (dispatch) run; click through
chat, clarification and approval in a browser against `./dev.sh --with-backend`. Then:
a stronger default model or a hint strategy that lets the planner finish multi-hop requests (G3),
Spring Boot 4.x, asymmetric keys between platform and agent, and the LangGraph adapter.
