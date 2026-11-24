-- Platform-owned durable state (PostgreSQL; also valid on H2 in PostgreSQL mode for unit tests).
-- Run state and conversations live in the agent service (contracts/openapi/agent-service.yaml).

-- One decision per (run, action hash): the approver decided what they saw (ADR-0006).
CREATE TABLE platform_approval_decisions (
    id          VARCHAR(36)              PRIMARY KEY,
    run_id      VARCHAR(40)              NOT NULL,
    tenant_id   VARCHAR(128)             NOT NULL,
    action_hash VARCHAR(64)              NOT NULL,
    decision    VARCHAR(16)              NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    decided_by  VARCHAR(128)             NOT NULL,
    reason      VARCHAR(500),
    decided_at  TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_platform_decision UNIQUE (run_id, action_hash)
);

CREATE INDEX idx_platform_decisions_tenant ON platform_approval_decisions (tenant_id, decided_at);

CREATE TABLE platform_audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    tenant_id   VARCHAR(128)             NOT NULL,
    subject     VARCHAR(128)             NOT NULL,
    action      VARCHAR(64)              NOT NULL,
    resource    VARCHAR(128),
    outcome     VARCHAR(64)              NOT NULL,
    request_id  VARCHAR(64)
);

CREATE INDEX idx_platform_audit_tenant ON platform_audit_log (tenant_id, occurred_at);
