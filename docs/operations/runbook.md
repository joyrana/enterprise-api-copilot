# Operations Runbook

Scope: the Python AI service (`python -m ai.api agent`), the local platform facade
(`python -m ai.api platform`, development only), and the sandbox gateway. The Spring Boot
platform will get its own runbook when it is built.

## Components and health

| Component | Health check | State |
|---|---|---|
| Platform facade | `GET /api/v1/health` | runs/approvals/idempotency in `COPILOT_STATE_DB` (SQLite) |
| Agent service | `GET /internal/v1/health` (reports skill count) | same store (required) |
| Sandbox gateway | `GET /healthz` | in memory (synthetic data, resets on restart) |
| CLI | `copilot doctor` | config + backend health + login |

## Correlating a request

Every API response carries `X-Request-Id` and `traceparent`. Error bodies repeat the
request id. With `COPILOT_TRACE_JSON=1`, spans are written as JSON lines to the
`copilot.trace` logger with `trace_id`, `span_id` and `parent_span_id`:

```bash
grep '"trace_id": "<id>"' service.log | jq -s 'sort_by(.parent_span_id)'
```

Upstream calls carry `X-Correlation-Id: <run_id>.<step>.<n>` and the same `traceparent`,
so gateway logs join on either value. Audit events (`copilot.audit` logger) carry
`correlation_id`, `run_id`, outcome and redacted arguments.

## Common incidents

**Runs stuck in `AWAITING_APPROVAL`.** Expected until an approver acts. List the queue
with `copilot approvals` (as a user with `approval:grant`). Approval tokens expire after
≤15 minutes; an expired one fails with `APPROVAL_INVALID`, so approve again from the queue.

**`409 action hash does not match`.** The pending action changed (or the client showed a
stale one). Re-fetch the run (`copilot runs get <id>`) and approve what is displayed.

**`APPROVAL_INVALID: approval was already used`.** Single-use enforcement working as
designed (a replayed or double-submitted approval). Nothing was executed twice; check the
audit log for the original `approval_id`.

**`UPSTREAM_UNAVAILABLE` / runs `FAILED` after retries.** The gateway returned 502/503/504
or was unreachable for all attempts (3, with backoff). Check the gateway health and the
`X-Correlation-Id` in its logs. Retrying the run is safe: writes reuse the idempotency key
and need a fresh approval.

**`DESTINATION_BLOCKED`.** The outbound allowlist rejected a host. Gateway hosts come only
from `COPILOT_GATEWAY_<ENV>_*`; never widen the allowlist to make a model-chosen URL work.

**`ENVIRONMENT_NOT_ALLOWED`.** The environment is not in `COPILOT_ENVIRONMENTS`, or the
action writes and the environment is not in `COPILOT_WRITE_ENVIRONMENTS`. Enabling
production writes is a change-managed decision, not an incident fix.

**`401 invalid or expired token` between platform and agent.** Service tokens live ≤5
minutes and need matching `COPILOT_SERVICE_TOKEN_KEY` on both sides; check clock skew
(>30 s is rejected).

## Routine tasks

**Rotate the approval signing key** (`COPILOT_APPROVAL_KEY`): deploy the new key; pending
approval tokens signed with the old key become invalid, so approvers re-approve from the
queue. No executed action is affected.

**Rotate service-token keys** (`COPILOT_SERVICE_TOKEN_KEY`): update platform and agent
together; in-flight tokens expire within 5 minutes.

**Back up state:** `sqlite3 "$COPILOT_STATE_DB" ".backup state-$(date +%F).db"` (safe
while running, WAL mode). Restoring an old backup re-enables approvals consumed after the
backup only if they are still unexpired (≤15 minutes) — restore with services stopped and
wait 15 minutes before restarting if that matters.

**Retention:** consumed approvals are purged after expiry automatically. Runs and
idempotency records are kept; prune with
`DELETE FROM runtime_runs WHERE updated_at < strftime('%s','now','-90 days')` per the
retention policy.

## Evaluation and benchmarks

```bash
python -m evals run --suite smoke          # PR gate (safety gates fail the run)
python -m evals run --suite full           # weekly
python -m evals.ablation --split test      # retrieval ablation (held-out)
python -m evals.judge calibrate            # judge harness (offline)
python -m evals.load --base-url http://127.0.0.1:8080
```
