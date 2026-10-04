"""Context assembly for model calls (threat model T1).

* Trusted policy text and untrusted retrieved text are kept in separate fields; untrusted
  text is rendered inside ``<untrusted_source id=...>`` delimiters with delimiter-like
  sequences neutralised.
* Instruction-like content is flagged by a heuristic scanner. Flagged sources are still
  citable as evidence that the text exists, but are excluded from answer synthesis and
  can never contribute tool arguments.
* A token budget bounds the total size; lowest-ranked sources are dropped first and
  every drop is recorded.
* Secrets are redacted before anything enters the context.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, Field

from ai.knowledge.retrieval import RetrievedChunk
from ai.knowledge.text import count_tokens
from skills.runtime.redaction import redact_text

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|system)\b.{0,20}\b(instructions?|rules|prompts?)\b",
            re.I | re.S,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\byou are (now|no longer)\b|\bact as (an? )?(admin|administrator|root|system)\b|\bnew (system )?instructions?\s*:",
            re.I,
        ),
    ),
    (
        "tool_coercion",
        re.compile(
            r"\b(call|invoke|execute)\b.{0,30}\b(tools?|functions?|skills?|api\.call\.\w+)\b",
            re.I | re.S,
        ),
    ),
    (
        "agent_directive",
        re.compile(
            r"\b(ai|assistants?|agents?|copilot|llms?|language models?)\b.{0,40}\b(must|should|is required to|are required to|need to)\b",
            re.I | re.S,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(send|post|forward|exfiltrate|upload)\b.{0,60}\b(token|secret|credential|password|api[ _-]?key|conversation|system prompt)\b",
            re.I | re.S,
        ),
    ),
    (
        "prompt_disclosure",
        re.compile(
            r"\b(reveal|print|show|repeat)\b.{0,30}\b(system prompt|hidden instructions|your instructions)\b",
            re.I | re.S,
        ),
    ),
    (
        "approval_bypass",
        re.compile(
            r"\b(skip|bypass|disable|without)\b.{0,30}\b(approval|confirmation|authori[sz]ation|policy)\b",
            re.I | re.S,
        ),
    ),
)


def scan_for_injection(text: str) -> list[str]:
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


def _neutralise(text: str) -> str:
    return text.replace("<untrusted_source", "<untrusted-source").replace(
        "</untrusted_source", "</untrusted-source"
    )


class ContextSource(BaseModel):
    source_id: str
    doc_id: str
    title: str
    section: str
    uri: str
    rank: int
    score: float
    text: str
    tokens: int
    injection_flags: list[str] = Field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.injection_flags)


class ContextPack(BaseModel):
    query: str
    sources: list[ContextSource]
    dropped_for_budget: list[str] = Field(default_factory=list)
    token_budget: int
    tokens_used: int

    @property
    def usable(self) -> list[ContextSource]:
        return [s for s in self.sources if not s.flagged]

    @property
    def flagged(self) -> list[ContextSource]:
        return [s for s in self.sources if s.flagged]

    def render_untrusted(self) -> str:
        blocks = []
        for s in self.sources:
            flag = f' flags="{",".join(s.injection_flags)}"' if s.flagged else ""
            blocks.append(
                f'<untrusted_source id="{s.source_id}" title="{s.title}"{flag}>\n'
                f"{_neutralise(s.text)}\n</untrusted_source>"
            )
        return "\n".join(blocks)


def build_context(
    query: str, retrieved: Sequence[RetrievedChunk], *, token_budget: int = 1200
) -> ContextPack:
    sources: list[ContextSource] = []
    dropped: list[str] = []
    used = 0
    for item in retrieved:
        text = redact_text(item.chunk.text)
        tokens = count_tokens(text)
        if used + tokens > token_budget:
            dropped.append(item.chunk.chunk_id)
            continue
        used += tokens
        sources.append(
            ContextSource(
                source_id=item.chunk.chunk_id,
                doc_id=item.chunk.doc_id,
                title=item.chunk.title,
                section=item.chunk.section,
                uri=item.chunk.uri,
                rank=item.rank,
                score=item.score,
                text=text,
                tokens=tokens,
                injection_flags=scan_for_injection(text),
            )
        )
    return ContextPack(
        query=query,
        sources=sources,
        dropped_for_budget=dropped,
        token_budget=token_budget,
        tokens_used=used,
    )
