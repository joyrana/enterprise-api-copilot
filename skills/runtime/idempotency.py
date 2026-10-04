"""Idempotency for side-effecting skills.

Keys are scoped per tenant. Reusing a key for the *same* action returns the stored result
(``replayed=True``); reusing it for a *different* action is rejected.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from skills.runtime.contracts import SkillResult


class IdempotencyRecord:
    __slots__ = ("action_hash", "result")

    def __init__(self, action_hash: str, result: SkillResult) -> None:
        self.action_hash = action_hash
        self.result = result


class IdempotencyStore(Protocol):
    async def get(self, tenant_id: str, key: str) -> IdempotencyRecord | None: ...

    async def put(self, tenant_id: str, key: str, record: IdempotencyRecord) -> None: ...

    def lock(self, tenant_id: str, key: str) -> asyncio.Lock: ...


class InMemoryIdempotencyStore:
    """Single-process store for tests and local runs (not durable)."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def get(self, tenant_id: str, key: str) -> IdempotencyRecord | None:
        return self._records.get((tenant_id, key))

    async def put(self, tenant_id: str, key: str, record: IdempotencyRecord) -> None:
        self._records[(tenant_id, key)] = record

    def lock(self, tenant_id: str, key: str) -> asyncio.Lock:
        return self._locks.setdefault((tenant_id, key), asyncio.Lock())
