"""System test: Go CLI binary → platform API (HTTP) → agent → sandbox gateway (HTTP).

Nothing is in-process or mocked between components: two uvicorn servers on loopback
ports and the compiled ``copilot`` binary. Skipped when ``go`` is not installed.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

from ai.agent.orchestrator import FileCheckpointStore
from ai.api.platform_app import PlatformConfig, create_platform_app
from ai.bootstrap import Settings, build_services
from sandbox.app import SandboxConfig, create_app
from skills.api.gateway import GatewayEnvironment

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("go") is None, reason="go not installed"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Server:
    def __init__(self, app: object, port: int) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )  # type: ignore[arg-type]
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, object]]:
    tmp = tmp_path_factory.mktemp("e2e")
    binary = tmp / "copilot"
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/copilot"], cwd=ROOT / "apps" / "cli", check=True
    )

    sandbox_cfg = SandboxConfig.default()
    client = sandbox_cfg.clients["acme-sandbox-app"]
    sandbox_app = create_app(sandbox_cfg)
    sport, pport = _free_port(), _free_port()
    settings = Settings(
        runtime_mode="test",
        gateways={
            "sandbox": GatewayEnvironment(
                name="sandbox",
                base_url=f"http://127.0.0.1:{sport}",
                token_url=f"http://127.0.0.1:{sport}/oauth/token",
                client_id=client.client_id,
                client_secret=SecretStr(client.client_secret),
                kind="sandbox",
            )
        },
        insecure_local_gateways=frozenset({"sandbox"}),
    )
    platform_app = create_platform_app(
        build_services(settings), PlatformConfig(run_store=FileCheckpointStore(tmp / "runs"))
    )
    with _Server(sandbox_app, sport), _Server(platform_app, pport):
        yield {
            "binary": binary,
            "url": f"http://127.0.0.1:{pport}",
            "tmp": tmp,
            "sandbox": sandbox_app,
        }


def cli(
    stack: dict[str, object], user: str, *args: str, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "XDG_CONFIG_HOME": str(Path(str(stack["tmp"])) / f"cfg-{user}"),
        "HOME": str(stack["tmp"]),
    }
    return subprocess.run(
        [str(stack["binary"]), "--backend-url", str(stack["url"]), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_cli_full_approval_workflow(stack: dict[str, object]) -> None:
    assert cli(stack, "alice", "login", "--user", "alice").returncode == 0
    assert cli(stack, "priya", "login", "--user", "priya").returncode == 0

    doctor = cli(stack, "alice", "doctor")
    assert doctor.returncode == 0 and "alice @ acme" in doctor.stdout

    search = cli(stack, "alice", "api", "search", "refund", "a", "payment", "--limit", "3")
    assert search.returncode == 0 and search.stdout.splitlines()[1].split()[1] == "refundPayment"

    payments = stack["sandbox"].state.sandbox.tenant("acme").payments  # type: ignore[attr-defined]
    before = len(payments)
    ask = cli(
        stack,
        "alice",
        "--output",
        "json",
        "ask",
        "Create a payment of ₹500 for customer cust_acm0001",
    )
    assert ask.returncode == 3, ask.stderr  # needs approval
    run = httpx.Response(200, content=ask.stdout).json()
    run_id = run["run_id"]
    assert run["pending_approval"]["environment"] == "sandbox" and len(payments) == before

    own = cli(stack, "alice", "runs", "approve", run_id, "--yes")
    assert own.returncode == 1 and "ACCESS_DENIED" in own.stderr and len(payments) == before

    queue = cli(stack, "priya", "approvals")
    assert run_id in queue.stdout

    approved = cli(stack, "priya", "runs", "approve", run_id, stdin="y\n")
    assert approved.returncode == 0, approved.stderr
    assert "HTTP 201" in approved.stdout and "$COPILOT_TOKEN" in approved.stdout
    assert len(payments) == before + 1

    history = cli(stack, "alice", "runs", "get", run_id)
    assert "approved approver=priya" in history.stdout

    config = Path(str(stack["tmp"])) / "cfg-alice" / "copilot" / "config.json"
    assert oct(config.stat().st_mode & 0o777) == "0o600"
