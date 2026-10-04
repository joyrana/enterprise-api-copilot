"""Documentation search with grounded, cited answers and abstention."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai.knowledge.answer import Answerer, ExtractiveAnswerer, GroundedAnswer
from ai.knowledge.context import build_context
from ai.knowledge.documents import SourceType
from ai.knowledge.retrieval import KnowledgeIndex
from skills.runtime.contracts import InvocationContext, SideEffect, SkillDefinition
from skills.runtime.policy import DOCS_READ


class DocsSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    mode: Literal["keyword", "dense", "hybrid"] = "hybrid"
    token_budget: int = Field(default=1200, ge=100, le=8000)


class SourceSummary(BaseModel):
    source_id: str
    doc_id: str
    title: str
    section: str
    uri: str
    rank: int
    score: float
    flagged: bool
    injection_flags: list[str]


class DocsSearchOutput(BaseModel):
    answer: GroundedAnswer
    sources: list[SourceSummary]
    dropped_for_budget: list[str]


def build_docs_skill(
    index: KnowledgeIndex, answerer: Answerer | None = None
) -> SkillDefinition[DocsSearchInput, DocsSearchOutput]:
    answerer = answerer or ExtractiveAnswerer()

    async def search(inp: DocsSearchInput, ctx: InvocationContext) -> DocsSearchOutput:
        retrieved = index.search(
            inp.query,
            tenant_id=ctx.principal.tenant_id,
            k=inp.k,
            mode=inp.mode,
            source_types={SourceType.MARKDOWN, SourceType.TEXT},
        )
        pack = build_context(inp.query, retrieved, token_budget=inp.token_budget)
        answer = answerer.answer(inp.query, pack)
        return DocsSearchOutput(
            answer=answer,
            sources=[
                SourceSummary(
                    source_id=s.source_id,
                    doc_id=s.doc_id,
                    title=s.title,
                    section=s.section,
                    uri=s.uri,
                    rank=s.rank,
                    score=s.score,
                    flagged=s.flagged,
                    injection_flags=s.injection_flags,
                )
                for s in pack.sources
            ],
            dropped_for_budget=pack.dropped_for_budget,
        )

    return SkillDefinition(
        id="docs.search",
        name="Search documentation",
        version="1.0.0",
        description="Answer questions from ingested documentation with citations, or abstain.",
        input_model=DocsSearchInput,
        output_model=DocsSearchOutput,
        handler=search,
        required_permissions=frozenset({DOCS_READ}),
        side_effect=SideEffect.READ,
        timeout_s=5,
        audit_required=False,
    )
