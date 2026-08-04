-- V1__init_schema.sql
-- Initial schema for Enterprise API Copilot
-- Managed by Flyway

-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Conversations ────────────────────────────────────────────────────────────
CREATE TABLE conversations (
    id          VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id     VARCHAR(128) NOT NULL,
    title       VARCHAR(256),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ
);

CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_conversations_created_at ON conversations(created_at DESC);

-- ─── Messages ─────────────────────────────────────────────────────────────────
CREATE TABLE messages (
    id              VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id VARCHAR(36)  NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(32)  NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);

-- ─── Executions ───────────────────────────────────────────────────────────────
CREATE TABLE executions (
    id              VARCHAR(36)   PRIMARY KEY DEFAULT gen_random_uuid()::text,
    conversation_id VARCHAR(36)   REFERENCES conversations(id),
    user_id         VARCHAR(128)  NOT NULL,
    natural_query   TEXT          NOT NULL,
    plan            JSONB,
    status          VARCHAR(32)   NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    api_method      VARCHAR(16),
    api_url         VARCHAR(2048),
    request_body    JSONB,
    response_status INT,
    response_body   JSONB,
    curl_equivalent TEXT,
    trace_id        VARCHAR(64),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_executions_user_id ON executions(user_id);
CREATE INDEX idx_executions_status ON executions(status);
CREATE INDEX idx_executions_created_at ON executions(created_at DESC);

-- ─── API Catalog ──────────────────────────────────────────────────────────────
CREATE TABLE api_catalog_entries (
    id           VARCHAR(36)  PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name         VARCHAR(256) NOT NULL,
    description  TEXT,
    method       VARCHAR(16)  NOT NULL,
    path         VARCHAR(2048) NOT NULL,
    tags         TEXT[],
    openapi_spec JSONB,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_catalog_entries_method ON api_catalog_entries(method);

COMMENT ON TABLE conversations IS 'Stores chat sessions between users and the API Copilot';
COMMENT ON TABLE messages IS 'Individual messages within a conversation';
COMMENT ON TABLE executions IS 'Records of API execution requests and their results';
COMMENT ON TABLE api_catalog_entries IS 'Indexed API definitions for discovery';
