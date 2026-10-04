"""Document and chunk model with stable identifiers and provenance.

* ``doc_id`` is supplied by the source (e.g. ``payments-v1`` or a relative doc path).
* ``chunk_id`` = ``{doc_id}@{version}#{ordinal}-{sha256(text)[:12]}`` — stable across
  re-ingestion of identical content, different when content or version changes.
* Every chunk carries ``tenant_id``; ``PUBLIC_TENANT`` content is visible to all tenants.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PUBLIC_TENANT = "*"


class SourceType(StrEnum):
    MARKDOWN = "markdown"
    OPENAPI_OPERATION = "openapi_operation"
    TEXT = "text"


class Document(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    source_type: SourceType
    title: str
    uri: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    doc_id: str
    version: str
    tenant_id: str
    source_type: SourceType
    title: str
    section: str
    uri: str
    ordinal: int
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def visible_to(self, tenant_id: str) -> bool:
        return self.tenant_id in (tenant_id, PUBLIC_TENANT)


def make_chunk_id(doc_id: str, version: str, ordinal: int, text: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{doc_id}@{version}#{ordinal}-{digest}"
