from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai.knowledge.answer import INSUFFICIENT_EVIDENCE, ExtractiveAnswerer
from ai.knowledge.chunking import ChunkingConfig, chunk_document
from ai.knowledge.context import build_context, scan_for_injection
from ai.knowledge.documents import PUBLIC_TENANT, Document, SourceType
from ai.knowledge.ingest import Ingestor, read_markdown_tree
from ai.knowledge.retrieval import HashingEmbedder, KnowledgeIndex, rrf

DOCS = Path(__file__).resolve().parents[2] / "sandbox" / "docs"


def _doc(text: str, doc_id: str = "d", version: str = "1", tenant: str = PUBLIC_TENANT) -> Document:
    return Document(
        doc_id=doc_id,
        version=version,
        tenant_id=tenant,
        source_type=SourceType.MARKDOWN,
        title="T",
        uri="doc://d",
        text=text,
    )


def test_chunk_ids_are_stable_and_content_addressed() -> None:
    text = "# A\n" + "alpha " * 300 + "\n# B\nbeta gamma"
    first = chunk_document(_doc(text), ChunkingConfig(max_tokens=100, overlap_tokens=20))
    second = chunk_document(_doc(text), ChunkingConfig(max_tokens=100, overlap_tokens=20))
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len(first) > 2 and first[-1].section == "B"
    changed = chunk_document(
        _doc(text, version="2"), ChunkingConfig(max_tokens=100, overlap_tokens=20)
    )
    assert first[0].chunk_id != changed[0].chunk_id


def test_fixed_strategy_windows_with_overlap() -> None:
    words = " ".join(f"w{i}" for i in range(200))
    chunks = chunk_document(
        _doc(words), ChunkingConfig(strategy="fixed", max_tokens=65, overlap_tokens=13)
    )
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert len(first) == 50 and first[-10:] == second[:10]


def test_incremental_ingest_update_delete() -> None:
    index = KnowledgeIndex()
    ing = Ingestor(index)
    r1 = ing.ingest([_doc("refunds take five days", "a"), _doc("orders ship daily", "b")])
    assert sorted(r1.added) == ["a", "b"]
    r2 = ing.ingest(
        [_doc("refunds take five days", "a"), _doc("orders ship weekly now", "b", version="2")]
    )
    assert r2.unchanged == ["a"] and r2.updated == ["b"]
    assert {c.version for c in index.chunks if c.doc_id == "b"} == {"2"}
    assert ing.delete("a").deleted == ["a"]
    assert all(c.doc_id != "a" for c in index.chunks)
    assert index.search("refunds", tenant_id="x", mode="keyword") == []


def test_tenant_filter_happens_before_scoring() -> None:
    index = KnowledgeIndex()
    Ingestor(index).ingest(
        [_doc("secret globex pricing fee", "g", tenant="globex"), _doc("public fee schedule", "p")]
    )
    hits = index.search("globex pricing fee", tenant_id="acme", k=10)
    assert [h.chunk.doc_id for h in hits] == ["p"]


def test_rrf_formula() -> None:
    fused = rrf([[1, 2], [2, 3]], k=60)
    assert fused[2] == pytest.approx(1 / 62 + 1 / 61)
    assert max(fused, key=lambda i: fused[i]) == 2


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    emb = HashingEmbedder(64)
    a, b = emb.embed(["create payment", "create payment"])
    assert (a == b).all() and abs(float((a * a).sum()) - 1.0) < 1e-5


def test_injection_scanner() -> None:
    flagged = (DOCS / "public" / "community-notes.md").read_text()
    assert {"override_instructions", "approval_bypass", "exfiltration"} <= set(
        scan_for_injection(flagged)
    )
    for clean in ("errors.md", "authentication.md", "payments-guide.md"):
        assert scan_for_injection((DOCS / "public" / clean).read_text()) == [], clean


def test_context_budget_redaction_and_delimiters() -> None:
    index = KnowledgeIndex()
    Ingestor(index).ingest(
        [
            _doc("Use header Authorization: Bearer abcdefghijklmnop to call refunds API", "a"),
            _doc("refunds " * 400, "b"),
        ]
    )
    pack = build_context("refunds", index.search("refunds", tenant_id="t", k=5), token_budget=200)
    assert pack.tokens_used <= 200 and pack.dropped_for_budget
    rendered = pack.render_untrusted()
    assert "abcdefghijklmnop" not in rendered and rendered.count("<untrusted_source") == len(
        pack.sources
    )


def test_answer_cites_or_abstains() -> None:
    index = KnowledgeIndex()
    docs, _ = read_markdown_tree(DOCS / "public", tenant_id=PUBLIC_TENANT)
    Ingestor(index).ingest(docs)
    answerer = ExtractiveAnswerer()
    pack = build_context(
        "minimum payment amount", index.search("minimum payment amount", tenant_id="acme")
    )
    good = answerer.answer("minimum payment amount", pack)
    assert not good.abstained and "100" in good.text and good.citations
    assert all(c.source_id in {s.source_id for s in pack.sources} for c in good.citations)
    q = "What is the capital of Australia?"
    none = answerer.answer(q, build_context(q, index.search(q, tenant_id="acme")))
    assert none.abstained and none.text == INSUFFICIENT_EVIDENCE


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
def test_markdown_reader_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.md").write_text("# ok\nfine")
    outside = tmp_path / "secret.md"
    outside.write_text("# secret\nnope")
    (root / "link.md").symlink_to(outside)
    docs, rejected = read_markdown_tree(root, tenant_id="t")
    assert [d.doc_id for d in docs] == ["docs/ok.md"] and "link.md" in rejected
