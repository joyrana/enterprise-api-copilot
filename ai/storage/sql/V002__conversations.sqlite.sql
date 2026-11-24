-- Conversations (G1). PostgreSQL twin: V002__conversations.postgres.sql
CREATE TABLE IF NOT EXISTS runtime_conversations (
    conversation_id TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_conversations_tenant ON runtime_conversations (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime_conversation_runs (
    run_id          TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES runtime_conversations (conversation_id),
    tenant_id       TEXT NOT NULL,
    added_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_conversation_runs_conv ON runtime_conversation_runs (conversation_id, added_at);
