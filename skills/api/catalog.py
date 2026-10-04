"""API catalog: OpenAPI operations with tenant visibility and hybrid search."""

from __future__ import annotations

from pydantic import BaseModel

from ai.knowledge.documents import PUBLIC_TENANT, SourceType
from ai.knowledge.ingest import Ingestor
from ai.knowledge.openapi import ApiOperation, ApiSpec, operation_documents
from ai.knowledge.retrieval import Embedder, KnowledgeIndex, RetrievalMode


class CatalogHit(BaseModel):
    operation: ApiOperation
    source_id: str
    score: float
    rank: int


class ApiCatalog:
    def __init__(self, embedder: Embedder | None = None) -> None:
        self.index = KnowledgeIndex(embedder)
        self._ingestor = Ingestor(self.index)
        self._ops: dict[str, tuple[ApiOperation, str]] = {}

    def register(self, spec: ApiSpec, *, tenant_id: str = PUBLIC_TENANT) -> None:
        for op in spec.operations:
            existing = self._ops.get(op.operation_id)
            if existing and existing[0].api_id != spec.api_id:
                raise ValueError(
                    f"operationId '{op.operation_id}' already registered by {existing[0].api_id}"
                )
            self._ops[op.operation_id] = (op, tenant_id)
        self._ingestor.ingest(operation_documents(spec, tenant_id=tenant_id))

    def get(self, operation_id: str, *, tenant_id: str) -> ApiOperation | None:
        entry = self._ops.get(operation_id)
        if entry is None or entry[1] not in (tenant_id, PUBLIC_TENANT):
            return None
        return entry[0]

    def operations(self, *, tenant_id: str) -> list[ApiOperation]:
        return [op for op, t in self._ops.values() if t in (tenant_id, PUBLIC_TENANT)]

    def search(
        self, query: str, *, tenant_id: str, k: int = 5, mode: RetrievalMode = "hybrid"
    ) -> list[CatalogHit]:
        hits = self.index.search(
            query, tenant_id=tenant_id, k=k, mode=mode, source_types={SourceType.OPENAPI_OPERATION}
        )
        out: list[CatalogHit] = []
        for hit in hits:
            op = self.get(str(hit.chunk.metadata.get("operation_id")), tenant_id=tenant_id)
            if op is not None:
                out.append(
                    CatalogHit(
                        operation=op, source_id=hit.chunk.chunk_id, score=hit.score, rank=hit.rank
                    )
                )
        return out
