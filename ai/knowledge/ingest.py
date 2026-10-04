"""Ingestion entry points: Markdown directories and OpenAPI specs (incremental, path-safe)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ai.knowledge.chunking import ChunkingConfig, chunk_document
from ai.knowledge.documents import Chunk, Document, SourceType
from ai.knowledge.openapi import ApiSpec, operation_documents
from ai.knowledge.retrieval import KnowledgeIndex

MAX_DOC_BYTES = 500_000


class IngestionReport(BaseModel):
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    rejected: dict[str, str] = Field(default_factory=dict)
    chunks: int = 0


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def read_markdown_tree(
    root: Path, *, tenant_id: str, version: str = "1"
) -> tuple[list[Document], dict[str, str]]:
    """Read ``*.md`` under ``root``. Paths resolving outside ``root`` are rejected (T10)."""
    root = root.resolve()
    docs: list[Document] = []
    rejected: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        resolved = path.resolve()
        rel = str(path.relative_to(root))
        if not resolved.is_relative_to(root):
            rejected[rel] = "path escapes ingestion root"
            continue
        if resolved.stat().st_size > MAX_DOC_BYTES:
            rejected[rel] = "document exceeds size limit"
            continue
        text = resolved.read_text(encoding="utf-8")
        docs.append(
            Document(
                doc_id=f"docs/{rel}",
                version=version,
                tenant_id=tenant_id,
                source_type=SourceType.MARKDOWN,
                title=_title(text, rel),
                uri=f"doc://{rel}",
                text=text,
            )
        )
    return docs, rejected


class Ingestor:
    """Tracks document versions/hashes so re-ingestion is incremental."""

    def __init__(self, index: KnowledgeIndex, config: ChunkingConfig | None = None) -> None:
        self.index = index
        self.config = config or ChunkingConfig()
        self._hashes: dict[str, tuple[str, str]] = {}  # doc_id -> (version, content hash)

    def ingest(self, docs: list[Document]) -> IngestionReport:
        report = IngestionReport()
        pending: list[Chunk] = []
        for doc in docs:
            state = (doc.version, doc.content_hash)
            previous = self._hashes.get(doc.doc_id)
            if previous == state:
                report.unchanged.append(doc.doc_id)
                continue
            config = (
                self.config
                if doc.source_type is not SourceType.OPENAPI_OPERATION
                else ChunkingConfig(max_tokens=4000)
            )
            chunks = chunk_document(doc, config)
            pending.extend(chunks)
            (report.updated if previous else report.added).append(doc.doc_id)
            self._hashes[doc.doc_id] = state
        if pending:
            self.index.add(pending)
        report.chunks = len(self.index.chunks)
        return report

    def ingest_spec(self, spec: ApiSpec, *, tenant_id: str) -> IngestionReport:
        return self.ingest(operation_documents(spec, tenant_id=tenant_id))

    def delete(self, doc_id: str) -> IngestionReport:
        report = IngestionReport()
        if self.index.delete_document(doc_id) or doc_id in self._hashes:
            report.deleted.append(doc_id)
        self._hashes.pop(doc_id, None)
        report.chunks = len(self.index.chunks)
        return report
