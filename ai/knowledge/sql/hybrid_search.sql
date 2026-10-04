-- Hybrid retrieval with Reciprocal Rank Fusion (k = 60), mirroring ai/knowledge/retrieval.py.
-- psql variables: :'tenant' :'query' :'qvec' (pgvector text literal) :pool :k
-- Tenant filtering happens before either ranking (threat model T6).
-- With HNSW + filters, enable iterative scans so filtered queries still return enough rows:
SET hnsw.iterative_scan = relaxed_order;

WITH visible AS (
    SELECT chunk_id, tsv, embedding
    FROM knowledge.chunks
    WHERE tenant_id IN (:'tenant', '*')
),
q AS (SELECT websearch_to_tsquery('english', :'query') AS tsq, (:'qvec')::vector AS vec),
kw AS (
    SELECT v.chunk_id,
           row_number() OVER (ORDER BY ts_rank_cd(v.tsv, q.tsq) DESC, v.chunk_id) AS r
    FROM visible v, q
    WHERE v.tsv @@ q.tsq
    ORDER BY r
    LIMIT :pool
),
dn AS (
    SELECT v.chunk_id,
           row_number() OVER (ORDER BY v.embedding <=> q.vec, v.chunk_id) AS r
    FROM visible v, q
    ORDER BY r
    LIMIT :pool
),
fused AS (
    SELECT chunk_id,
           sum(1.0 / (60 + r)) AS score,
           min(r) FILTER (WHERE src = 'kw') AS kw_rank,
           min(r) FILTER (WHERE src = 'dn') AS dn_rank
    FROM (SELECT chunk_id, r, 'kw' AS src FROM kw UNION ALL SELECT chunk_id, r, 'dn' FROM dn) u
    GROUP BY chunk_id
)
SELECT chunk_id, round(score::numeric, 6) AS score, kw_rank, dn_rank
FROM fused
ORDER BY score DESC, coalesce(kw_rank, 1000000), coalesce(dn_rank, 1000000), chunk_id
LIMIT :k;
