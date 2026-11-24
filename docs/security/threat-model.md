# Threat Model

- **Version:** 3 (2026-10-04; v1 2026-10-03)
- **Method:** STRIDE-style asset/boundary analysis plus OWASP LLM risk categories.
- **Scope:** Python AI service (agent + skill runtime), sandbox/Apigee gateway path,
  knowledge ingestion, evaluation artifacts. Platform backend, CLI and web app are listed
  where they own a control.

## Assets

| Asset | Why it matters |
|---|---|
| Gateway/API credentials (client secrets, bearer tokens) | Direct access to enterprise APIs |
| Approval signing key | Forging it bypasses human approval |
| Tenant data in knowledge store and API responses | Confidentiality across tenants |
| Audit trail | Non-repudiation, incident response |
| Skill registry and policy table | Defines what the agent may do |

## Trust boundaries

1. User ↔ CLI/web (authenticated via platform).
2. Platform ↔ AI service (service-to-service authentication).
3. AI service ↔ model provider (prompts leave the boundary).
4. AI service ↔ gateway ↔ upstream APIs (outbound network).
5. Ingested content (OpenAPI specs, Markdown) → knowledge store → model context.

## Threats and controls

Status: **I** = implemented and tested in this repo; **P** = planned; **B** = blocked in current environment.

| # | Threat | Control | Where | Status |
|---|---|---|---|---|
| T1 | Prompt injection in retrieved docs / API descriptions instructs the agent to call tools or reveal data | Retrieved text is wrapped in delimited `<untrusted_source>` blocks; instruction-like patterns are flagged and excluded from tool-argument derivation; the model sees only the skills the intent resolver allows for the run's intent, every decision is validated (allowed skill, describe-before-call, grounded arguments) and any tool call still passes policy + approval | `ai/knowledge/context.py`, `skills/runtime/runtime.py` | I |
| T2 | Malicious OpenAPI description (huge spec, `$ref` loops, server URL pointing at internal hosts) | Size limits on ingestion; `$ref` resolution depth-bounded and local-only; spec `servers` are **ignored** for execution — the gateway base URL comes only from configuration | `ai/knowledge/openapi.py`, `skills/api/gateway.py` | I |
| T3 | Tool abuse / excessive agency | Required permissions per skill; side-effect classes; plans capped at N steps; tool-call budget per run | `skills/runtime/*`, `ai/agent/orchestrator.py` | I |
| T4 | Approval bypass or reuse | Approval token = HMAC over canonical action hash incl. arguments, environment, tenant, subject; expiry; single-use store; mismatch → reject | `skills/runtime/approvals.py`, `ai/storage/sql_store.py` | I (single use enforced by a primary-key insert in the durable store; survives restarts and concurrent processes) |
| T5 | Environment switch after approval | Environment is part of the action hash; environment allowlist checked before policy | `skills/runtime/runtime.py` | I |
| T6 | Unauthorized data access / cross-tenant retrieval | Every document/chunk carries `tenant_id`; retrievers filter before scoring; sandbox data partitioned per tenant | `ai/knowledge/*`, `sandbox/app.py` | I |
| T7 | Secret exfiltration via logs, traces, model context, generated code | Redaction of bearer tokens, JWTs, API-key patterns and secret-named fields before audit/log/model — for model requests in one place (`sanitize_request` in `generate_structured`, every attempt, every stage; JWTs become `<JWT>`); SDK generator emits `$COPILOT_TOKEN` placeholders, never header values | `skills/runtime/redaction.py`, `ai/models/base.py`, `skills/api/sdk_generator.py` | I |
| T8 | SSRF / unsafe URL fetching | Only `https` (or `http` for explicitly allowlisted local hosts); host allowlist; DNS-resolved address must not be private/loopback/link-local/metadata unless the host is explicitly allowlisted as local; no redirects; response-size cap; timeouts | `skills/runtime/http_safety.py` | I |
| T9 | Command injection | No shell execution anywhere in skills; generated cURL is quoted with `shlex.quote` and never executed | `skills/api/sdk_generator.py` | I |
| T10 | Path traversal in doc ingestion | Ingestion reads only under a configured root; resolved paths must stay inside it | `ai/knowledge/ingest.py` | I |
| T11 | Unsafe generated-code execution | Generated snippets are returned as text only; no evaluation path exists | design | I |
| T12 | Replay / duplicate side effects | Idempotency keys required for WRITE/DESTRUCTIVE; conflicting reuse rejected; sandbox honours `Idempotency-Key` | `skills/runtime/idempotency.py`, `sandbox/app.py` | I |
| T13 | Supply chain | Pinned ranges, lockfiles, Dependabot, Trivy pinned by version, least-privilege CI tokens | `.github/` | P (lockfiles B: registries unreachable) |
| T14 | Sensitive telemetry leakage | Spans carry sizes, counts, ids and `gen_ai.*` usage — never prompt text, payloads or tokens by default | `ai/telemetry.py` | I |
| T15 | Model grants itself permissions | Principal comes from the caller context, never from model output; policy table is read-only at runtime | `skills/runtime/policy.py` | I |
| T16 | Spoofed principal between platform and AI service | HS256 service token (aud `copilot-agent`, ≤5 min, required claims, pinned algorithm); principal only from verified claims, never request bodies | `ai/api/auth.py`, `ai/api/agent_app.py` | I (shared-secret; asymmetric/mTLS planned for production) |
| T18 | Approving something other than what was shown | Approval request must echo the displayed `action_hash` (409 on mismatch); approver needs `approval:grant`; per-run lock prevents double approval | `ai/api/runs.py` | I |
| T19 | User token theft from CLI/web | CLI: config 0600 in 0700 dir, refuses world-readable config, tokens via stdin not argv, refuses tokens over plain HTTP to non-loopback hosts, no redirects. Web: sessionStorage (tab-scoped), same-origin only | `apps/cli/internal/{config,client}`, `apps/frontend/src/api/session.ts` | I (XSS hardening of the web app P) |
| T21 | Untraceable incidents / log injection via trace ids | Only well-formed W3C `traceparent` values are accepted (all-zero ids rejected); spans export ids, durations and scalar attributes only | `ai/telemetry.py`, `ai/api/http.py` | I |
| T20 | Oversized / malformed API requests | 64 KiB body limit (413), strict schemas with `extra=forbid` (400), uniform `ApiError` without internals | `ai/api/http.py` | I |
| T17 | Denial of wallet / resource exhaustion | Step, tool-call, retry and wall-clock budgets; response-size limits | orchestrator, http_safety | I (token/cost quotas P) |

### LLM-specific threats (ADR-0011)

| # | Threat | Control | Tests | Status |
|---|---|---|---|---|
| T22 | Injection through documents, API responses or earlier assistant text steers the planner | Untrusted content reaches the model only in the delimited `untrusted_context` (never the system prompt); the resolver bounds the skills a run may use; documentation output is never a grounding source; earlier assistant replies are context only | `test_llm_agent::test_planner_cannot_reach_skills_outside_the_resolved_set`, `test_conversations::test_documentation_and_failed_calls_never_become_grounding_sources`, `test_conversations::test_earlier_assistant_text_is_not_a_grounding_source`, eval `adv-001` (the injected community note) | I |
| T23 | Credentials sent to the model provider (tokens pasted in a request, secrets in tool output) | One sanitizer applied to every request attempt, including repair retries; JWTs → `<JWT>`, other shapes → `[REDACTED]`; the planner substitutes the real token after the model call; payload tracing is opt-in, redacted and capped | `test_llm_secrets` (every stage, repair, tool output, each credential shape), `test_llm_tracing::test_payload_capture_is_redacted_and_capped`, eval `adv-004` | I (pattern-based: novel credential shapes can slip through) |
| T24 | Model denial of service / wallet: runs pile onto a one-request-at-a-time model | Concurrency limiter with a bounded, tenant-fair queue; new runs get `429` + `Retry-After` when full; queue wait is excluded from the run's budget; step, tool-call and time budgets (the time budget runs on a monotonic clock, so sleep/wake or an NTP step cannot end a healthy run); an identical call that already failed is not retried; a skill rejected twice is withdrawn for the run | `test_concurrency` (fairness, bound, cancellation, 429), contract `test_full_model_queue_is_429_with_retry_after`, `test_llm_agent::test_a_wall_clock_jump_does_not_exhaust_the_run_budget`, `test_llm_agent::test_an_identical_call_that_already_failed_is_not_retried` | I (single-process limiter; per-tenant quotas P) |
| T25 | Hallucinated or injected argument values | Values must appear in what the user typed, a clarification answer, or a successful API result of the same run (recorded with provenance); everything else is dropped and the run asks; the approval summary shows the concrete target (path parameters filled in, query string), exact body and where API-derived values came from | `test_llm_agent::test_execution_is_validated_grounded_and_resumed_after_approval`, `test_conversations::test_values_from_an_earlier_api_result_are_grounded_with_provenance`, `test_llm_agent::test_undescribed_calls_are_described_first_and_ids_come_from_results`, eval `adv-002` | I |
| T26 | UI spoofing: the model puts misleading text, a fake approval button or a hidden approval in the reply | Components are chosen by name from a registry; the server builds every prop from real step output and validates it against the component's schema; `approval_request` and `clarification` are server-controlled and cannot be selected or suppressed; the approval hash shown is the run's, not the component's; identifiers and operation names in the reply must appear in the run's evidence (user text, successful step output, server draft), otherwise the responder gets one corrective retry and what remains is masked as `[unverified]` | `test_llm_agent::test_agentic_discovery_builds_ui_from_real_output`, `test_llm_agent::test_invented_identifiers_in_the_reply_are_retried_then_masked`, `test_ui_manifest`, CLI `TestRenderersCoverEveryComponent`, History role-gating test | I |
| T27 | Conversation memory poisoning, cross-tenant leakage, or a colleague steering someone else's run (confused deputy) | Conversations are private to their creator (another user, same tenant or not, gets a 404 and cannot read or post into one); only the run's requester may answer its clarification (403 otherwise), because the answer grounds values and the run keeps the requester's permissions; history is bounded and redacted; only text the user typed grounds values; writes still need approval | `test_conversations` (cross-tenant, durable SQL, clarification + approval), contract `test_conversations_and_clarification` on both implementations (viewer `vic` gets 403/404) | I |
| T28 | The platform's approval minting is abused (wrong approver, other tenant's run) | Spring checks the approver role and that the hash matches the pending action before minting; the token is HMAC-bound to hash + tenant; the agent verifies and consumes it once; decisions are recorded in PostgreSQL | `PlatformApiTest::onlyAnApproverWhoSawTheExactActionCanApprove`, `ApprovalMinterTest` (known-answer vs the runtime's algorithm), contract `test_run_approve_flow` on both implementations | I (shared HMAC key; asymmetric/KMS P) |
| T29 | Run events leak across tenants or expose secrets | `GET /runs/{id}/events` is tenant-scoped (404 before any byte) and sends the same redacted timeline as the run view | `test_concurrency`, contract `test_async_run_and_event_stream` | I |

## Residual risks (known, accepted for now)

- The deterministic local PDP is a stand-in; production policy must come from the platform.
- Injection detection is heuristic; it reduces but does not eliminate risk. The structural
  controls (T3–T5, T15) are the real defence.
- The default model runs locally (mlx-lm), so no data leaves the machine; the Anthropic adapter is opt-in and its provider terms are not assessed. Secret masking is pattern-based and lossy, so a credential with an unknown shape can still reach a provider.
- A 4B model is wrong or malformed some of the time. That costs usefulness (retries, refused steps, a clarification), never authorization — but the approval summary a human reads is the last check on a grounded-but-wrong value.
- The model limiter is per process. Several agent replicas multiply the allowed concurrency; per-tenant quotas are not built.
- The Spring backend's dev-token endpoint is off unless `copilot.auth.dev-token-enabled` is set (the `local` profile); production must configure `copilot.auth.oidc-issuer-uri`.
- Service tokens use a shared HS256 secret; production should use asymmetric keys or mTLS.
- The local platform facade's dev-token endpoint is only safe because the facade refuses to run outside local/test mode.
