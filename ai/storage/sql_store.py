"""Durable stores for runs, consumed approvals and idempotency records.

One SQL store implements three runtime interfaces:

* ``CheckpointStore`` — run state, listed per tenant through an index on
  ``(tenant_id, created_at)`` instead of scanning files;
* ``ApprovalStore`` — single use enforced by the database: consuming inserts the approval
  id under a primary key, so two processes cannot both consume the same approval;
* ``IdempotencyStore`` — results keyed by ``(tenant_id, key)``.

It runs today on the standard library's ``sqlite3`` (local/dev, WAL mode). The SQL is
portable (``ON CONFLICT``, bound parameters) and the schema has a PostgreSQL twin in
``ai/storage/sql/V001__runtime.postgres.sql``; a psycopg connection factory plugs in
through :class:`SqlDialect` when the driver can be installed (STATUS.md).

Concurrency note: the per-key ``asyncio.Lock`` serialises idempotent execution inside one
process. Across processes, double execution of a write is prevented by the single-use
approval (every write consumes a fresh approval atomically); the upstream gateway's own
``Idempotency-Key`` handling is the second line.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.agent.contracts import RunState
from skills.runtime.contracts import SkillResult
from skills.runtime.idempotency import IdempotencyRecord

SCHEMA_SQLITE = Path(__file__).resolve().parent / "sql" / "V001__runtime.sqlite.sql"

# Portable statements ("?" placeholders, rewritten per dialect). Tested on SQLite and,
# via PREPARE, on PostgreSQL (tests/integration/test_runtime_sql_postgres.py).
STATEMENTS: dict[str, str] = {
    "save_run": (
        "INSERT INTO runtime_runs (run_id, tenant_id, status, created_at, updated_at, state_json) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (run_id) DO UPDATE SET status = excluded.status, "
        "updated_at = excluded.updated_at, state_json = excluded.state_json"
    ),
    "load_run": "SELECT state_json FROM runtime_runs WHERE run_id = ?",
    "list_runs": (
        "SELECT state_json FROM runtime_runs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?"
    ),
    "list_runs_status": (
        "SELECT state_json FROM runtime_runs WHERE tenant_id = ? AND status = ? "
        "ORDER BY created_at DESC LIMIT ?"
    ),
    "purge_approvals": "DELETE FROM runtime_used_approvals WHERE expires_at < ?",
    "consume_approval": (
        "INSERT INTO runtime_used_approvals (approval_id, expires_at, used_at) VALUES (?, ?, ?) "
        "ON CONFLICT (approval_id) DO NOTHING"
    ),
    "get_idem": (
        "SELECT action_hash, result_json FROM runtime_idempotency "
        "WHERE tenant_id = ? AND idem_key = ?"
    ),
    "put_idem": (
        "INSERT INTO runtime_idempotency "
        "(tenant_id, idem_key, action_hash, result_json, created_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (tenant_id, idem_key) DO NOTHING"
    ),
}


@dataclass(frozen=True)
class SqlDialect:
    name: str
    placeholder: str  # "?" for sqlite3, "%s" for psycopg

    def q(self, sql: str) -> str:
        return sql.replace("?", self.placeholder)


SQLITE = SqlDialect("sqlite", "?")
POSTGRES = SqlDialect("postgres", "%s")


def _created_at(state: RunState) -> float:
    for event in state.events:
        if event.kind == "created":
            return float(event.detail.get("at", state.started_at))
    return state.started_at


class SqlRuntimeStore:
    def __init__(
        self,
        connect: Callable[[], Any],
        dialect: SqlDialect = SQLITE,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._conn = connect()
        self._dialect = dialect
        self._clock = clock
        self._mutex = threading.Lock()
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @classmethod
    def sqlite(cls, path: Path | str, **kw: Any) -> SqlRuntimeStore:
        def connect() -> sqlite3.Connection:
            if str(path) != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(SCHEMA_SQLITE.read_text(encoding="utf-8"))
            return conn

        return cls(connect, SQLITE, **kw)

    @contextmanager
    def _tx(self) -> Iterator[Any]:
        with self._mutex:
            cur = self._conn.cursor()
            cur.execute("BEGIN IMMEDIATE" if self._dialect is SQLITE else "BEGIN")
            try:
                yield cur
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            else:
                cur.execute("COMMIT")

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with self._mutex:
            cur = self._conn.cursor()
            cur.execute(self._dialect.q(sql), params)
            return list(cur.fetchall())

    # ── CheckpointStore ──────────────────────────────────────────────────────
    def save(self, state: RunState) -> None:
        with self._tx() as cur:
            cur.execute(
                self._dialect.q(STATEMENTS["save_run"]),
                (
                    state.run_id,
                    state.principal.tenant_id,
                    state.status.value,
                    _created_at(state),
                    self._clock(),
                    state.model_dump_json(),
                ),
            )

    def load(self, run_id: str) -> RunState | None:
        rows = self._query(STATEMENTS["load_run"], (run_id,))
        return RunState.model_validate_json(rows[0][0]) if rows else None

    def list_runs(
        self, tenant_id: str, *, status: str | None = None, limit: int = 1000
    ) -> list[RunState]:
        if status is None:
            rows = self._query(STATEMENTS["list_runs"], (tenant_id, limit))
        else:
            rows = self._query(STATEMENTS["list_runs_status"], (tenant_id, status, limit))
        return [RunState.model_validate_json(r[0]) for r in rows]

    # ── ApprovalStore ────────────────────────────────────────────────────────
    async def consume(self, approval_id: str, expires_at: float) -> bool:
        now = self._clock()
        with self._tx() as cur:
            cur.execute(self._dialect.q(STATEMENTS["purge_approvals"]), (now,))
            cur.execute(
                self._dialect.q(STATEMENTS["consume_approval"]), (approval_id, expires_at, now)
            )
            return bool(cur.rowcount == 1)

    # ── IdempotencyStore ─────────────────────────────────────────────────────
    async def get(self, tenant_id: str, key: str) -> IdempotencyRecord | None:
        rows = self._query(STATEMENTS["get_idem"], (tenant_id, key))
        if not rows:
            return None
        return IdempotencyRecord(rows[0][0], SkillResult.model_validate_json(rows[0][1]))

    async def put(self, tenant_id: str, key: str, record: IdempotencyRecord) -> None:
        with self._tx() as cur:
            cur.execute(
                self._dialect.q(STATEMENTS["put_idem"]),
                (
                    tenant_id,
                    key,
                    record.action_hash,
                    record.result.model_dump_json(),
                    self._clock(),
                ),
            )

    def lock(self, tenant_id: str, key: str) -> asyncio.Lock:
        return self._locks.setdefault((tenant_id, key), asyncio.Lock())

    def close(self) -> None:
        with self._mutex:
            self._conn.close()
