# skills — skill runtime and built-in skills

Every tool call — from the agent or from MCP — goes through `runtime.SkillRuntime.invoke`
(ADR-0006). Skills never see unauthorized calls.

| Module | Responsibility |
|---|---|
| `runtime/contracts.py` | `SkillDefinition`: id, version, typed I/O, permissions, side-effect class, timeout, retry, idempotency, audit, error codes, preflight |
| `runtime/runtime.py` | Enforcement order: input → environment allowlist → policy → preflight → approval → idempotency → execute → output contract → audit |
| `runtime/policy.py` | `PolicyDecisionPort` + `LocalPolicyEngine` (dev/test stand-in for the platform PDP) |
| `runtime/approvals.py`, `approval_service.py` | Action-bound, expiring, single-use approval tokens |
| `runtime/http_safety.py` | SSRF-safe outbound HTTP |
| `runtime/redaction.py` | Secret redaction |
| `api/` | `api.search`, `api.describe`, `api.call.{read,write,delete}`, `code.generate`, gateway adapter |
| `jwt/` | `token.inspect` |
| `docs/` | `docs.search` |
| `mcp_server.py` | MCP server generated from the registry |

Adding a skill: define Pydantic input/output models, build a `SkillDefinition`, register
it in `ai/bootstrap.py`, and add runtime-level tests (authorization, failure, contract).
