-- Runtime state for the AI service (PostgreSQL). Same tables/columns as the SQLite schema,
-- so the statements in ai/storage/sql_store.py run unchanged with the POSTGRES dialect.
-- Timestamps are epoch seconds (double precision) to match RunState.
CREATE TABLE IF NOT EXISTS runtime_runs (
    run_id      TEXT PRIMARY KEY CHECK (run_id ~ '^run_[0-9a-f]{16}$'),
    tenant_id   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('RUNNING','AWAITING_APPROVAL','NEEDS_CLARIFICATION','COMPLETED','REJECTED','FAILED')),
    created_at  DOUBLE PRECISION NOT NULL,
    updated_at  DOUBLE PRECISION NOT NULL,
    state_json  JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_runs_tenant_created ON runtime_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runtime_runs_tenant_status ON runtime_runs (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime_used_approvals (
    approval_id TEXT PRIMARY KEY,
    expires_at  DOUBLE PRECISION NOT NULL,
    used_at     DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_idempotency (
    tenant_id   TEXT NOT NULL,
    idem_key    TEXT NOT NULL,
    action_hash CHAR(64) NOT NULL,
    result_json JSONB NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (tenant_id, idem_key)
);
