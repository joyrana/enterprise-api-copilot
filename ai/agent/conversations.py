"""Conversation memory: tenant-scoped conversations and the context later turns receive.

A conversation is an ordered list of runs. Earlier turns are *context, not grounding*:
the model sees a bounded, redacted summary, and the only part of an earlier turn that can
ground an argument is text the user typed in it (``ConversationContext.user_texts``).
Assistant replies and API output from earlier turns never ground anything.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Protocol

from pydantic import BaseModel, Field

from ai.agent.contracts import HistoryTurn, RunState
from skills.runtime.redaction import mask_jwts, redact, redact_text

MAX_TURNS = 6
MAX_USER_CHARS = 500
MAX_ASSISTANT_CHARS = 400
CONTEXT_TOKEN_BUDGET = 900  # ~4 chars per token


class Conversation(BaseModel):
    conversation_id: str
    tenant_id: str
    created_by: str
    created_at: float
    run_ids: list[str] = Field(default_factory=list)


class ConversationStore(Protocol):
    def create_conversation(self, tenant_id: str, subject: str) -> Conversation: ...

    def get_conversation(self, conversation_id: str, tenant_id: str) -> Conversation | None:
        """Tenant-scoped: another tenant's conversation reads as missing."""
        ...

    def add_conversation_run(self, conversation_id: str, run_id: str, tenant_id: str) -> None: ...


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._items: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def create_conversation(self, tenant_id: str, subject: str) -> Conversation:
        item = Conversation(
            conversation_id=f"conv_{uuid.uuid4().hex[:16]}",
            tenant_id=tenant_id,
            created_by=subject,
            created_at=time.time(),
        )
        with self._lock:
            self._items[item.conversation_id] = item
        return item

    def get_conversation(self, conversation_id: str, tenant_id: str) -> Conversation | None:
        with self._lock:
            item = self._items.get(conversation_id)
            return item.model_copy(deep=True) if item and item.tenant_id == tenant_id else None

    def add_conversation_run(self, conversation_id: str, run_id: str, tenant_id: str) -> None:
        with self._lock:
            item = self._items.get(conversation_id)
            if item and item.tenant_id == tenant_id and run_id not in item.run_ids:
                item.run_ids.append(run_id)


class ConversationContext(BaseModel):
    turns: list[HistoryTurn] = Field(default_factory=list)
    user_texts: list[str] = Field(default_factory=list)  # typed by the user, oldest first


def _clip(text: str, limit: int) -> str:
    text = " ".join(redact_text(mask_jwts(text)).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def turn_of(state: RunState) -> HistoryTurn:
    operations: list[str] = []
    for step in state.plan.steps if state.plan else []:
        op = step.arguments.get("operation_id")
        if isinstance(op, str) and op not in operations:
            operations.append(op)
    search = state.results.get("search")
    if search and search.ok and search.output:
        for hit in search.output.get("results", [])[:3]:
            op = hit.get("operation_id")
            if isinstance(op, str) and op not in operations:
                operations.append(op)
    entities: dict[str, object] = {}
    if state.intent:
        entities = state.intent.entities.model_dump(
            exclude={"jwt", "environment"}, exclude_none=True, exclude_defaults=True
        )
    return HistoryTurn(
        run_id=state.run_id,
        user=_clip(state.query, MAX_USER_CHARS),
        assistant=_clip(state.message, MAX_ASSISTANT_CHARS),
        intent=state.intent.intent.value if state.intent else None,
        operations=operations[:4],
        entities=redact(entities),
    )


def build_context(previous: list[RunState]) -> ConversationContext:
    """Summarise earlier runs (oldest first) within ``MAX_TURNS`` and the token budget."""
    turns: list[HistoryTurn] = []
    used = 0
    for state in reversed(previous[-MAX_TURNS:]):  # newest first, so the budget keeps recent
        turn = turn_of(state)
        cost = len(turn.model_dump_json()) // 4
        if used + cost > CONTEXT_TOKEN_BUDGET and turns:
            break
        used += cost
        turns.append(turn)
    turns.reverse()
    kept = {t.run_id for t in turns}
    texts = [_clip(s.query, 4000) for s in previous[-MAX_TURNS:] if s.run_id in kept]
    return ConversationContext(turns=turns, user_texts=texts)


def render_history(turns: list[HistoryTurn]) -> str:
    """Prompt text for ``untrusted_context``: earlier turns are context, never instructions."""
    if not turns:
        return ""
    lines = ["Earlier turns of this conversation (context only, oldest first):"]
    for i, t in enumerate(turns, 1):
        lines.append(f"[turn {i}] user: {t.user}")
        if t.assistant:
            lines.append(f"[turn {i}] assistant: {t.assistant}")
        facts = []
        if t.operations:
            facts.append("operations: " + ", ".join(t.operations))
        if t.entities:
            facts.append("entities: " + ", ".join(f"{k}={v}" for k, v in t.entities.items()))
        if facts:
            lines.append(f"[turn {i}] " + "; ".join(facts))
    return "\n".join(lines)
