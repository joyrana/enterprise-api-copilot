-- Conversations (G1). Same tables/columns as the SQLite schema (V002__conversations.sqlite.sql).
CREATE TABLE IF NOT EXISTS runtime_conversations (
    conversation_id TEXT PRIMARY KEY CHECK (conversation_id ~ '^conv_[0-9a-f]{16}$'),
    tenant_id       TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_conversations_tenant ON runtime_conversations (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS runtime_conversation_runs (
    run_id          TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES runtime_conversations (conversation_id),
    tenant_id       TEXT NOT NULL,
    added_at        DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_conversation_runs_conv ON runtime_conversation_runs (conversation_id, added_at);
