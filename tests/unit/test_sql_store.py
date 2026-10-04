"""Durable SQL runtime store (SQLite): runs, single-use approvals, idempotency."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from ai.agent.contracts import RunEvent, RunState, RunStatus
from ai.storage.sql_store import SqlRuntimeStore
from skills.runtime.approval_service import ApprovalService
from skills.runtime.contracts import Principal, SkillResult
from skills.runtime.errors import SkillErrorCode
from skills.runtime.idempotency import IdempotencyRecord
from skills.runtime.policy import LocalPolicyEngine
from tests.support import build_harness

ACME = Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"}))
GLOBEX = Principal(subject="gina", tenant_id="globex", roles=frozenset({"developer"}))


def _run(i: int, principal: Principal, status: RunStatus = RunStatus.COMPLETED) -> RunState:
    state = RunState(
        run_id=f"run_{i:016x}",
        query=f"q{i}",
        principal=principal,
        environment="sandbox",
        status=status,
    )
    state.events.append(RunEvent(kind="created", detail={"at": 1000.0 + i}))
    return state


def test_runs_round_trip_ordering_filters_and_isolation(tmp_path: Path) -> None:
    store = SqlRuntimeStore.sqlite(tmp_path / "rt.db")
    for i in range(5):
        store.save(_run(i, ACME, RunStatus.AWAITING_APPROVAL if i % 2 else RunStatus.COMPLETED))
    store.save(_run(9, GLOBEX))
    assert [r.run_id for r in store.list_runs("acme", limit=3)] == [
        f"run_{i:016x}" for i in (4, 3, 2)
    ]
    assert [r.query for r in store.list_runs("acme", status="AWAITING_APPROVAL")] == ["q3", "q1"]
    assert [r.query for r in store.list_runs("globex")] == ["q9"]
    updated = _run(1, ACME, RunStatus.COMPLETED)
    store.save(updated)  # upsert keeps one row
    assert len(store.list_runs("acme")) == 5
    assert store.load("run_0000000000000001").status is RunStatus.COMPLETED  # type: ignore[union-attr]
    assert store.load("run_ffffffffffffffff") is None


def test_state_survives_reopen(tmp_path: Path) -> None:
    SqlRuntimeStore.sqlite(tmp_path / "rt.db").save(_run(7, ACME))
    assert SqlRuntimeStore.sqlite(tmp_path / "rt.db").load("run_0000000000000007") is not None


async def test_approval_single_use_across_connections_and_threads(tmp_path: Path) -> None:
    a = SqlRuntimeStore.sqlite(tmp_path / "rt.db")
    b = SqlRuntimeStore.sqlite(tmp_path / "rt.db")  # second "process"
    assert await a.consume("appr-1", 9e12) is True
    assert await b.consume("appr-1", 9e12) is False

    results: list[bool] = []

    def worker(store: SqlRuntimeStore) -> None:
        results.append(asyncio.run(store.consume("appr-race", 9e12)))

    threads = [threading.Thread(target=worker, args=(s,)) for s in (a, b) * 8]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1 and len(results) == 16


async def test_expired_approvals_are_purged(tmp_path: Path) -> None:
    now = [1000.0]
    store = SqlRuntimeStore.sqlite(tmp_path / "rt.db", clock=lambda: now[0])
    assert await store.consume("old", 1001.0)
    now[0] = 2000.0
    await store.consume("other", 3000.0)  # triggers purge
    rows = store._query("SELECT approval_id FROM runtime_used_approvals", ())
    assert [r[0] for r in rows] == ["other"]


async def test_idempotency_round_trip_first_write_wins(tmp_path: Path) -> None:
    store = SqlRuntimeStore.sqlite(tmp_path / "rt.db")
    result = SkillResult(
        skill_id="s", skill_version="1", ok=True, output={"id": 1}, correlation_id="c"
    )
    await store.put("acme", "k", IdempotencyRecord("h1", result))
    await store.put("acme", "k", IdempotencyRecord("h2", result))
    got = await store.get("acme", "k")
    assert got is not None and got.action_hash == "h1" and got.result.output == {"id": 1}
    assert await store.get("globex", "k") is None


async def test_runtime_replay_and_approval_reuse_survive_restart(tmp_path: Path) -> None:
    """A write executed before a restart is replayed (not re-executed) after it, and its
    approval cannot be reused — the guarantees no longer depend on process memory."""
    db = tmp_path / "rt.db"
    h = build_harness()
    rt = h.services.runtime
    store = SqlRuntimeStore.sqlite(db)
    rt._approvals, rt._idempotency = store, store
    args = {
        "operation_id": "createPayment",
        "body": {"amount": 10000, "currency": "INR", "customer_id": "cust_acm0001"},
    }
    pending = await rt.invoke("api.call.write", args, h.ctx(idempotency_key="k-restart"))
    approver = Principal(subject="priya", tenant_id="acme", roles=frozenset({"approver"}))
    token = await ApprovalService(h.services.approval_signer, LocalPolicyEngine()).approve(
        approver=approver,
        action_hash=pending.action_hash or "",
        tenant_id="acme",
        environment="sandbox",
    )
    assert (
        await rt.invoke(
            "api.call.write", args, h.ctx(idempotency_key="k-restart", approval_token=token)
        )
    ).ok
    payments = h.app.state.sandbox.tenant("acme").payments
    count = len(payments)

    restarted = SqlRuntimeStore.sqlite(db)  # fresh store == process restart
    rt._approvals, rt._idempotency = restarted, restarted
    replay = await rt.invoke(
        "api.call.write", args, h.ctx(idempotency_key="k-restart", approval_token=token)
    )
    assert replay.ok and replay.replayed and len(payments) == count
    reuse = await rt.invoke(
        "api.call.write", args, h.ctx(idempotency_key="k-other", approval_token=token)
    )
    assert (
        reuse.error
        and reuse.error.code is SkillErrorCode.APPROVAL_INVALID
        and len(payments) == count
    )
