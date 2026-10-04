"""Knowledge schema migration and hybrid SQL against a real PostgreSQL + pgvector.

Driven through ``psql`` (the Python driver is a Phase 4 dependency). Opt-in: set
``COPILOT_TEST_PGURL`` to a disposable database URL, e.g.
``postgresql://api_copilot:<password>@localhost:5432/api_copilot_test``.
The test drops and recreates the ``knowledge`` schema in that database.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ai.knowledge.chunking import ChunkingConfig, chunk_document
from ai.knowledge.documents import PUBLIC_TENANT, Chunk
from ai.knowledge.ingest import read_markdown_tree
from ai.knowledge.retrieval import HashingEmbedder, KnowledgeIndex

ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "ai" / "knowledge" / "sql"
PGURL = os.environ.get("COPILOT_TEST_PGURL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PGURL or shutil.which("psql") is None, reason="COPILOT_TEST_PGURL/psql not available"
    ),
]


def psql(*args: str, sql: str | None = None) -> str:
    cmd = ["psql", str(PGURL), "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", *args]
    proc = subprocess.run(cmd, input=sql, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def _corpus() -> list[Chunk]:
    docs, _ = read_markdown_tree(ROOT / "sandbox" / "docs" / "public", tenant_id=PUBLIC_TENANT)
    for tenant in ("acme", "globex"):
        tdocs, _ = read_markdown_tree(
            ROOT / "sandbox" / "docs" / "tenants" / tenant, tenant_id=tenant
        )
        docs += [d.model_copy(update={"doc_id": f"{tenant}/{d.doc_id}"}) for d in tdocs]
    config = ChunkingConfig()
    return [c for d in docs for c in chunk_document(d, config)]


@pytest.fixture(scope="module")
def loaded() -> list[Chunk]:
    psql(sql="DROP SCHEMA IF EXISTS knowledge CASCADE;")
    psql("-f", str(SQL / "V001__knowledge.sql"))
    chunks = _corpus()
    emb = HashingEmbedder()
    vectors = emb.embed([f"{c.title} {c.section} {c.text}" for c in chunks])
    statements = []
    for doc_id in sorted({(c.tenant_id, c.doc_id, c.version, c.title, c.uri) for c in chunks}):
        tenant, did, ver, title, uri = doc_id
        statements.append(
            "INSERT INTO knowledge.documents (tenant_id, doc_id, version, source_type, title, uri, content_sha256) "
            f"VALUES ({_q(tenant)}, {_q(did)}, {_q(ver)}, 'markdown', {_q(title)}, {_q(uri)}, {_q('0' * 64)});"
        )
    for c, v in zip(chunks, vectors, strict=True):
        statements.append(
            "INSERT INTO knowledge.chunks (chunk_id, tenant_id, doc_id, version, ordinal, section, body, embedding, embedder, embedder_version) "
            f"VALUES ({_q(c.chunk_id)}, {_q(c.tenant_id)}, {_q(c.doc_id)}, {_q(c.version)}, {c.ordinal}, {_q(c.section)}, "
            f"{_q(c.title + ' ' + c.text)}, {_q(_vec(v.tolist()))}, {_q(emb.name)}, {_q(emb.version)});"
        )
    psql(sql="\n".join(statements))
    return chunks


def hybrid(tenant: str, query: str, k: int = 5) -> list[str]:
    qvec = _vec(HashingEmbedder().embed([query])[0].tolist())
    out = psql(
        "-v",
        f"tenant={tenant}",
        "-v",
        f"query={query}",
        "-v",
        f"qvec={qvec}",
        "-v",
        "pool=50",
        "-v",
        f"k={k}",
        "-f",
        str(SQL / "hybrid_search.sql"),
    )
    return [line.split("|")[0] for line in out.splitlines() if "|" in line]


def test_migration_creates_indexes(loaded: list[Chunk]) -> None:
    indexes = psql(
        sql="SELECT indexname FROM pg_indexes WHERE schemaname='knowledge' ORDER BY 1;"
    ).splitlines()
    assert {"chunks_embedding_hnsw", "chunks_tsv_idx", "chunks_tenant_doc_idx"} <= set(indexes)
    assert int(psql(sql="SELECT count(*) FROM knowledge.chunks;")) == len(loaded)


def test_dense_ranking_matches_in_process(loaded: list[Chunk]) -> None:
    query = "rate limit exceeded retry after header"
    qvec = _vec(HashingEmbedder().embed([query])[0].tolist())
    sql_top = psql(
        sql=f"SET enable_indexscan = off; SELECT chunk_id FROM knowledge.chunks WHERE tenant_id IN ('acme','*') "
        f"ORDER BY embedding <=> '{qvec}'::vector, chunk_id LIMIT 5;"
    ).splitlines()
    index = KnowledgeIndex(HashingEmbedder(), dense_min_score=-1.0)
    index.add(loaded)
    local_top = [r.chunk.chunk_id for r in index.search(query, tenant_id="acme", k=5, mode="dense")]
    assert sql_top[:3] == local_top[:3]


def test_hybrid_sql_finds_relevant_and_respects_tenants(loaded: list[Chunk]) -> None:
    top = hybrid("acme", "429 too many requests retry")
    assert any("errors.md" in cid for cid in top[:3])
    leaked = hybrid("acme", "Globex negotiated processing fee settlement window")
    assert not any(cid.startswith("globex/") for cid in leaked)
    own = hybrid("globex", "Globex negotiated processing fee settlement window")
    assert own and own[0].startswith("globex/")


def test_document_delete_cascades(loaded: list[Chunk]) -> None:
    psql(sql="DELETE FROM knowledge.documents WHERE doc_id = 'docs/community-notes.md';")
    assert (
        psql(sql="SELECT count(*) FROM knowledge.chunks WHERE doc_id = 'docs/community-notes.md';")
        == "0"
    )
