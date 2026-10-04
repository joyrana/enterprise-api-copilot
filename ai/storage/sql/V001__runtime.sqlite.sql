-- Runtime state (local/dev, SQLite). PostgreSQL twin: V001__runtime.postgres.sql
CREATE TABLE IF NOT EXISTS runtime_runs (
    run_id      TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    state_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_runs_tenant_created ON runtime_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS runtime_runs_tenant_status ON runtime_runs (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime_used_approvals (
    approval_id TEXT PRIMARY KEY,
    expires_at  REAL NOT NULL,
    used_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_idempotency (
    tenant_id   TEXT NOT NULL,
    idem_key    TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (tenant_id, idem_key)
);
