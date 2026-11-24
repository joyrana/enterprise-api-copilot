"""The runtime store's exact SQL statements, executed on PostgreSQL via PREPARE/EXECUTE.

There is no Python Postgres driver in this environment, so this drives ``psql``. It proves
the PostgreSQL schema applies and that every statement in ``STATEMENTS`` (rewritten to
``$n`` placeholders) parses, executes and has the expected semantics — in particular
single-use approvals via ``ON CONFLICT DO NOTHING``. Opt-in via ``COPILOT_TEST_PGURL``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ai.storage.sql_store import STATEMENTS

SQL_DIR = Path(__file__).resolve().parents[2] / "ai" / "storage" / "sql"
SQL = SQL_DIR / "V001__runtime.postgres.sql"
SQL_V2 = SQL_DIR / "V002__conversations.postgres.sql"
PGURL = os.environ.get("COPILOT_TEST_PGURL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PGURL or shutil.which("psql") is None, reason="COPILOT_TEST_PGURL/psql not available"
    ),
]


def psql(sql: str) -> list[str]:
    proc = subprocess.run(
        ["psql", str(PGURL), "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [line for line in proc.stdout.splitlines() if line]


def numbered(sql: str) -> str:
    counter = iter(range(1, 100))
    return re.sub(r"\?", lambda _: f"${next(counter)}", sql)


def lit(value: object) -> str:
    return (
        str(value) if isinstance(value, int | float) else "'" + str(value).replace("'", "''") + "'"
    )


def run(name: str, *params: object) -> list[str]:
    return psql(
        f"PREPARE s AS {numbered(STATEMENTS[name])};\n"
        f"EXECUTE s({', '.join(lit(p) for p in params)});\nDEALLOCATE s;"
    )


@pytest.fixture(scope="module", autouse=True)
def schema() -> None:
    psql(
        "DROP TABLE IF EXISTS runtime_conversation_runs, runtime_conversations, runtime_runs, "
        "runtime_used_approvals, runtime_idempotency;"
    )
    psql(SQL.read_text(encoding="utf-8"))
    psql(SQL_V2.read_text(encoding="utf-8"))
    psql(SQL_V2.read_text(encoding="utf-8"))  # idempotent: the store re-applies it on start


def test_runs_statements() -> None:
    for i, (tenant, status) in enumerate(
        [("acme", "COMPLETED"), ("acme", "AWAITING_APPROVAL"), ("globex", "COMPLETED")]
    ):
        run("save_run", f"run_{i:016x}", tenant, status, 1000 + i, 1000 + i, f'{{"n": {i}}}')
    run("save_run", "run_0000000000000000", "acme", "FAILED", 1000, 2000, '{"n": 0, "v": 2}')
    assert run("load_run", "run_0000000000000000") == ['{"n": 0, "v": 2}']
    assert run("list_runs", "acme", 10) == ['{"n": 1}', '{"n": 0, "v": 2}']
    assert run("list_runs_status", "acme", "AWAITING_APPROVAL", 10) == ['{"n": 1}']
    with pytest.raises(AssertionError):
        run("save_run", "not-a-run-id", "acme", "COMPLETED", 1, 1, "{}")  # CHECK constraint


def test_approval_single_use_and_purge() -> None:
    run("consume_approval", "a1", 5000, 1000)
    run("consume_approval", "a1", 5000, 1001)  # conflict → no-op
    assert psql(
        "SELECT count(*), min(used_at) FROM runtime_used_approvals WHERE approval_id = 'a1';"
    ) == ["1|1000"]
    run("purge_approvals", 6000)
    assert psql("SELECT count(*) FROM runtime_used_approvals;") == ["0"]


def test_idempotency_first_write_wins() -> None:
    run("put_idem", "acme", "k", "a" * 64, '{"ok": true}', 1)
    run("put_idem", "acme", "k", "b" * 64, '{"ok": false}', 2)
    assert run("get_idem", "acme", "k") == ["a" * 64 + '|{"ok": true}']
    assert run("get_idem", "globex", "k") == []


def test_conversation_statements_are_tenant_scoped() -> None:
    cid = "conv_0123456789abcdef"
    run("create_conversation", cid, "acme", "alice", 1000)
    assert run("get_conversation", cid, "acme") == [f"{cid}|acme|alice|1000"]
    assert run("get_conversation", cid, "globex") == []  # another tenant: indistinguishable
    # add_conversation_run (run, conv, tenant, at, conv, tenant): only into the owner's conversation
    run("add_conversation_run", "run_0000000000000001", cid, "acme", 1001, cid, "acme")
    run(
        "add_conversation_run", "run_0000000000000001", cid, "acme", 1002, cid, "acme"
    )  # idempotent
    run("add_conversation_run", "run_0000000000000002", cid, "globex", 1003, cid, "globex")
    assert run("conversation_runs", cid, "acme") == ["run_0000000000000001"]
    assert run("conversation_runs", cid, "globex") == []
    with pytest.raises(AssertionError):
        run("create_conversation", "bogus", "acme", "alice", 1)  # CHECK constraint on the id
