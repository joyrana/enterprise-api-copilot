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
| T1 | Prompt injection in retrieved docs / API descriptions instructs the agent to call tools or reveal data | Retrieved text is wrapped in delimited `<untrusted_source>` blocks; instruction-like patterns are flagged and excluded from tool-argument derivation; tool selection is deterministic for known intents; any tool call still passes policy + approval | `ai/knowledge/context.py`, `skills/runtime/runtime.py` | I |
| T2 | Malicious OpenAPI description (huge spec, `$ref` loops, server URL pointing at internal hosts) | Size limits on ingestion; `$ref` resolution depth-bounded and local-only; spec `servers` are **ignored** for execution — the gateway base URL comes only from configuration | `ai/knowledge/openapi.py`, `skills/api/gateway.py` | I |
| T3 | Tool abuse / excessive agency | Required permissions per skill; side-effect classes; plans capped at N steps; tool-call budget per run | `skills/runtime/*`, `ai/agent/orchestrator.py` | I |
| T4 | Approval bypass or reuse | Approval token = HMAC over canonical action hash incl. arguments, environment, tenant, subject; expiry; single-use store; mismatch → reject | `skills/runtime/approvals.py`, `ai/storage/sql_store.py` | I (single use enforced by a primary-key insert in the durable store; survives restarts and concurrent processes) |
| T5 | Environment switch after approval | Environment is part of the action hash; environment allowlist checked before policy | `skills/runtime/runtime.py` | I |
| T6 | Unauthorized data access / cross-tenant retrieval | Every document/chunk carries `tenant_id`; retrievers filter before scoring; sandbox data partitioned per tenant | `ai/knowledge/*`, `sandbox/app.py` | I |
| T7 | Secret exfiltration via logs, traces, model context, generated code | Redaction of bearer tokens, JWTs, API-key patterns and secret-named fields before audit/log/model; SDK generator emits `$COPILOT_TOKEN` placeholders, never header values | `skills/runtime/redaction.py`, `skills/api/sdk_generator.py` | I |
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

## Residual risks (known, accepted for now)

- The deterministic local PDP is a stand-in; production policy must come from the platform.
- Injection detection is heuristic; it reduces but does not eliminate risk. The structural
  controls (T3–T5, T15) are the real defence.
- No model-provider adapters exist yet, so data-retention terms of providers are not assessed.
- Service tokens use a shared HS256 secret; production should use asymmetric keys or mTLS.
- The local platform facade's dev-token endpoint is only safe because the facade refuses to run outside local/test mode.
