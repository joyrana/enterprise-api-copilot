"""Grounded answering with citations and explicit abstention.

``ExtractiveAnswerer`` is the deterministic offline answerer: it selects sentences from
*unflagged* sources whose term overlap with the question passes a threshold, cites each
one, and abstains with "insufficient evidence" otherwise. It never adds text that is not
in a source, so faithfulness is structural; relevance is what evaluation measures.
An LLM answerer will implement the same ``Answerer`` protocol and be evaluated against it.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

from ai.knowledge.context import ContextPack
from ai.knowledge.text import tokenize

INSUFFICIENT_EVIDENCE = (
    "I don't have enough evidence in the available documentation to answer that."
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


class Citation(BaseModel):
    marker: int
    source_id: str
    doc_id: str
    title: str
    uri: str


class GroundedAnswer(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    reason: str | None = None
    flagged_source_ids: list[str] = Field(default_factory=list)
    answerer: str = "extractive-v1"


class Answerer(Protocol):
    def answer(self, query: str, pack: ContextPack) -> GroundedAnswer: ...


class ExtractiveAnswerer:
    name = "extractive-v1"

    def __init__(self, *, min_overlap: float = 0.5, max_sentences: int = 3) -> None:
        self.min_overlap = min_overlap
        self.max_sentences = max_sentences

    def answer(self, query: str, pack: ContextPack) -> GroundedAnswer:
        flagged = [s.source_id for s in pack.flagged]
        terms = set(tokenize(query))
        if not terms:
            return GroundedAnswer(
                text=INSUFFICIENT_EVIDENCE,
                abstained=True,
                reason="empty query",
                flagged_source_ids=flagged,
            )
        candidates: list[tuple[float, int, int, str, str]] = []
        for source in pack.usable:
            for position, sentence in enumerate(_SENTENCE.split(source.text)):
                sentence = sentence.strip().lstrip("#-* ").strip()
                if len(sentence) < 20:
                    continue
                overlap = len(terms & set(tokenize(sentence))) / len(terms)
                if overlap >= self.min_overlap:
                    candidates.append((overlap, source.rank, position, sentence, source.source_id))
        if not candidates:
            return GroundedAnswer(
                text=INSUFFICIENT_EVIDENCE,
                abstained=True,
                reason="no retrieved passage sufficiently matches the question",
                flagged_source_ids=flagged,
            )
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        by_id = {s.source_id: s for s in pack.usable}
        markers: dict[str, int] = {}
        parts: list[str] = []
        seen: set[str] = set()
        for _overlap, _rank, _pos, sentence, source_id in candidates:
            if sentence in seen:
                continue
            seen.add(sentence)
            marker = markers.setdefault(source_id, len(markers) + 1)
            parts.append(f"{sentence} [{marker}]")
            if len(parts) >= self.max_sentences:
                break
        citations = [
            Citation(
                marker=m,
                source_id=sid,
                doc_id=by_id[sid].doc_id,
                title=by_id[sid].title,
                uri=by_id[sid].uri,
            )
            for sid, m in sorted(markers.items(), key=lambda kv: kv[1])
        ]
        return GroundedAnswer(text=" ".join(parts), citations=citations, flagged_source_ids=flagged)
