"""Configurable chunking strategies.

* ``heading`` (default for Markdown): split on Markdown headings, then pack paragraphs up
  to ``max_tokens`` with ``overlap_tokens`` of trailing context carried forward.
* ``fixed``: sliding window of ``max_tokens`` words with overlap, ignoring structure.
* OpenAPI operations are already one chunk per operation (see ``openapi.py``).

Defaults are placeholders until the retrieval benchmark picks values (ADR-0007).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai.knowledge.documents import Chunk, Document, make_chunk_id
from ai.knowledge.text import count_tokens

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: Literal["heading", "fixed"] = "heading"
    max_tokens: int = Field(default=220, ge=20, le=4000)
    overlap_tokens: int = Field(default=30, ge=0)

    def label(self) -> str:
        return f"{self.strategy}-{self.max_tokens}-{self.overlap_tokens}"


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [("", text.strip())]
    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        sections.append((m.group(2).strip(), body))
    return sections


def _windows(words: list[str], size: int, overlap: int) -> list[list[str]]:
    if len(words) <= size:
        return [words]
    step = max(1, size - overlap)
    out = []
    for start in range(0, len(words), step):
        out.append(words[start : start + size])
        if start + size >= len(words):
            break
    return out


def chunk_document(doc: Document, config: ChunkingConfig) -> list[Chunk]:
    # count_tokens ~ words * 1.3, so convert the token budget into a word budget.
    word_budget = max(10, int(config.max_tokens / 1.3))
    word_overlap = min(int(config.overlap_tokens / 1.3), word_budget - 1)
    pieces: list[tuple[str, str]] = []
    if config.strategy == "fixed":
        for window in _windows(doc.text.split(), word_budget, word_overlap):
            pieces.append(("", " ".join(window)))
    else:
        for heading, body in _sections(doc.text):
            if not body:
                continue
            prefix = f"{heading}\n" if heading else ""
            if count_tokens(prefix + body) <= config.max_tokens:
                pieces.append((heading, prefix + body))
                continue
            for window in _windows(body.split(), word_budget, word_overlap):
                pieces.append((heading, prefix + " ".join(window)))
    chunks: list[Chunk] = []
    for ordinal, (section, text) in enumerate(pieces):
        chunks.append(
            Chunk(
                chunk_id=make_chunk_id(doc.doc_id, doc.version, ordinal, text),
                doc_id=doc.doc_id,
                version=doc.version,
                tenant_id=doc.tenant_id,
                source_type=doc.source_type,
                title=doc.title,
                section=section,
                uri=doc.uri,
                ordinal=ordinal,
                text=text,
                metadata=dict(doc.metadata),
            )
        )
    return chunks
