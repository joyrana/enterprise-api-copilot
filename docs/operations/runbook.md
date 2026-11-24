# Operations Runbook

Scope: the Python AI service (`python -m ai.api agent`), the platform API (the Spring Boot
backend, or the local Python facade `python -m ai.api platform`, development only), the
LLM server (mlx-lm) and the sandbox gateway.

## Components and health

| Component | Health check | State |
|---|---|---|
| Platform (Spring) | `GET /api/v1/health` (`"service":"copilot-platform-spring"`), `/actuator/health` | PostgreSQL: approval decisions + audit log (Flyway) |
| Platform facade (dev) | `GET /api/v1/health` | runs/approvals/idempotency in `COPILOT_STATE_DB` (SQLite) |
| LLM server (mlx-lm) | `curl :8000/v1/models` | none (model weights in `~/.cache/huggingface`) |
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

## Operating the LLM (mlx-lm)

```bash
pip install mlx-lm   # Apple Silicon
mlx_lm.server --model mlx-community/Qwen3-4B-Instruct-2507-4bit --port 8000
```

`--port` is required (the server's default, 8080, is the platform's). `COPILOT_LLM_MODEL` must
equal `--model`, or the server downloads and loads a second model on the first request.

**Capacity.** The server handles one request at a time and prompt processing dominates:
a run is typically 13–25 s and 4–7 model calls (p50 ≈ 17 s, p95 ≈ 37 s in the evaluation).
The agent therefore admits one model call at a time (`COPILOT_LLM_CONCURRENCY=1`) and queues
up to `COPILOT_LLM_QUEUE_MAX` (8) runs, served round-robin across tenants. At roughly 8 s
per call, a full queue means a new run waits about a minute: it is refused instead with `429
MODEL_BUSY` and `Retry-After`. Time in the queue is recorded as `model.queue_wait_s` on the
run and is not counted against its 240 s budget. Raise concurrency only for a server that
batches requests; several agent replicas multiply the limit because it is per process.

**Failure modes.**

| Symptom | Meaning | Action |
|---|---|---|
| Run `FAILED`: "language model … is unavailable" | mlx-lm unreachable or HTTP error (`model_failed` event, stage given) | Start/restart the server; retry. There is no rules fallback by design. |
| Run `FAILED`: "returned output I couldn't use" | Two invalid JSON replies in a row (the model ignores `response_format`; the agent validates and repairs once) | Retry; if frequent, check the model name and `repair_rate` in the evaluation |
| Run `COMPLETED` with "The action succeeded, but the summary could not be generated" | A write executed, then a later model call failed (`summary_unavailable` event) | The action happened; read the API response component or `copilot runs get`; do **not** repeat it |
| `429 MODEL_BUSY` | The model queue is full | Retry after `Retry-After`; look at `model_call` event latencies |
| Many `plan_rejected` / `skill_withdrawn` events | The model keeps proposing steps the validator refuses | Inspect the prompt version in `model_call` events; run the live evaluation |

**Tracing the model.** Each call is an `llm.generate` span under the run span (stage, provider,
model, prompt version, tokens, latency, outcome `ok|repaired|invalid_json|unavailable`) and a
`model_call` run event. To see prompts and replies locally set `COPILOT_LLM_TRACE_PAYLOADS=1`
(optionally `COPILOT_LLM_TRACE_FILE`, default `.copilot/llm-payloads.jsonl`): redacted,
capped at 6000 characters per field, local file only, off by default.

## Watching a run

`POST /api/v1/runs?mode=async` returns 202 immediately; `GET /api/v1/runs/{id}/events` streams
the timeline (SSE, `Last-Event-ID` resumes). The stream ends after a `status` event once the
run has settled (a `settled` timeline event). Behind a proxy, disable response buffering
(`X-Accel-Buffering: no` is sent).

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

**Platform ↔ agent (Spring).** `502 AGENT_UNAVAILABLE` from the platform: the agent service is
down or `COPILOT_AGENT_URL` is wrong. `401` on every agent call: `COPILOT_SERVICE_TOKEN_KEY`
differs between the two. `APPROVAL_INVALID` right after an approve: `COPILOT_APPROVAL_KEY`
differs between the platform (signs) and the agent's runtime (verifies).

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
