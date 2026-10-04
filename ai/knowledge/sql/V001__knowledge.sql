-- Knowledge store owned by the Python AI service (ADR-0007).
-- Tenant rows are visible to that tenant; tenant_id '*' rows are public.
-- Embedding dimension matches the default HashingEmbedder (512). A different embedder
-- needs a new column/table per dimension; embedder name+version are stored per chunk.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS knowledge;

CREATE TABLE knowledge.documents (
    tenant_id       TEXT        NOT NULL,
    doc_id          TEXT        NOT NULL,
    version         TEXT        NOT NULL,
    source_type     TEXT        NOT NULL CHECK (source_type IN ('markdown', 'openapi_operation', 'text')),
    title           TEXT        NOT NULL,
    uri             TEXT        NOT NULL,
    content_sha256  CHAR(64)    NOT NULL,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, doc_id)
);

CREATE TABLE knowledge.chunks (
    chunk_id          TEXT        PRIMARY KEY,
    tenant_id         TEXT        NOT NULL,
    doc_id            TEXT        NOT NULL,
    version           TEXT        NOT NULL,
    ordinal           INTEGER     NOT NULL CHECK (ordinal >= 0),
    section           TEXT        NOT NULL DEFAULT '',
    body              TEXT        NOT NULL,
    embedding         vector(512) NOT NULL,
    embedder          TEXT        NOT NULL,
    embedder_version  TEXT        NOT NULL,
    tsv               TSVECTOR    GENERATED ALWAYS AS (to_tsvector('english', section || ' ' || body)) STORED,
    FOREIGN KEY (tenant_id, doc_id) REFERENCES knowledge.documents (tenant_id, doc_id) ON DELETE CASCADE
);

CREATE INDEX chunks_tenant_doc_idx ON knowledge.chunks (tenant_id, doc_id);
CREATE INDEX chunks_tsv_idx        ON knowledge.chunks USING gin (tsv);
-- pgvector defaults (m=16, ef_construction=64) until the retrieval benchmark selects values.
CREATE INDEX chunks_embedding_hnsw ON knowledge.chunks USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE knowledge.chunks IS 'Retrievable chunks; always filter by tenant_id IN ($tenant, ''*'') before ranking';
