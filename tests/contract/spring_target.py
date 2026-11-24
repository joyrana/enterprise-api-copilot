"""Run the platform contract suite against the Spring Boot implementation (Phase 6).

``spring_stack`` starts, all on loopback: the agent service (uvicorn, in this process, backed by
the in-process sandbox harness so tests can still inspect sandbox state), a PostgreSQL server
(a throwaway local instance, or ``COPILOT_SPRING_DB_URL`` such as a CI service container) and
the built Spring Boot jar. The same tests then run unchanged against it.

Enable with ``COPILOT_SPRING_JAR=apps/backend/target/api-copilot-backend-*.jar`` (or build the
jar and the default path is used). Java 21+ and, without ``COPILOT_SPRING_DB_URL``, a local
PostgreSQL (``initdb``/``pg_ctl`` on PATH or Homebrew) are required.
"""

from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn

from ai.agent.orchestrator import InMemoryCheckpointStore
from ai.api.agent_app import create_agent_app
from tests.support import Harness, build_harness

ROOT = Path(__file__).resolve().parents[2]
SERVICE_KEY = b"s" * 40
PLATFORM_KEY = b"p" * 32  # the key the contract tests forge/sign tokens with
APPROVAL_KEY = "contract-test-approval-key-" + "x" * 16  # shared by the agent runtime and Spring
PG_DIRS = ("/opt/homebrew/opt/postgresql@18/bin", "/opt/homebrew/opt/postgresql@17/bin")


def spring_jar() -> Path | None:
    explicit = os.environ.get("COPILOT_SPRING_JAR")
    candidates = (
        [explicit]
        if explicit
        else glob.glob(str(ROOT / "apps/backend/target/api-copilot-backend-*.jar"))
    )
    for item in candidates:
        if item and Path(item).is_file() and not item.endswith("-plain.jar"):
            return Path(item)
    return None


def _pg_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in PG_DIRS:
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return None


def unavailable_reason() -> str | None:
    if spring_jar() is None:
        return "Spring jar not built (cd apps/backend && mvn package) or COPILOT_SPRING_JAR unset"
    if shutil.which("java") is None:
        return "java not installed"
    if not os.environ.get("COPILOT_SPRING_DB_URL") and not (
        _pg_tool("initdb") and _pg_tool("pg_ctl")
    ):
        return "no PostgreSQL (set COPILOT_SPRING_DB_URL or install initdb/pg_ctl)"
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(url: str, seconds: float, what: str) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError(f"{what} did not become healthy at {url}")


@contextmanager
def _postgres(tmp: Path) -> Iterator[tuple[str, str, str]]:
    """(jdbc url, user, password) of a database the Spring app may migrate."""
    external = os.environ.get("COPILOT_SPRING_DB_URL")
    if external:
        yield (
            external,
            os.environ.get("COPILOT_SPRING_DB_USER", "copilot"),
            os.environ.get("COPILOT_SPRING_DB_PASSWORD", ""),
        )
        return
    initdb, pg_ctl = _pg_tool("initdb"), _pg_tool("pg_ctl")
    assert initdb and pg_ctl
    data, port = tmp / "pgdata", _free_port()
    subprocess.run(
        [initdb, "-D", str(data), "-A", "trust", "-U", "copilot", "-E", "UTF8"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-w",
            "-l",
            str(tmp / "pg.log"),
            "-o",
            f"-p {port} -k {tmp} -c listen_addresses=127.0.0.1",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    try:
        createdb = _pg_tool("createdb")
        assert createdb
        subprocess.run(
            [createdb, "-h", "127.0.0.1", "-p", str(port), "-U", "copilot", "copilot_contract"],
            check=True,
            capture_output=True,
        )
        yield f"jdbc:postgresql://127.0.0.1:{port}/copilot_contract", "copilot", ""
    finally:
        subprocess.run([pg_ctl, "-D", str(data), "-m", "immediate", "stop"], capture_output=True)


@contextmanager
def spring_stack() -> Iterator[tuple[httpx.Client, Harness]]:
    jar = spring_jar()
    assert jar is not None
    harness = build_harness(approval_key=APPROVAL_KEY)
    agent_app = create_agent_app(
        harness.services, service_key=SERVICE_KEY, store=InMemoryCheckpointStore()
    )
    agent_port, platform_port = _free_port(), _free_port()
    server = uvicorn.Server(
        uvicorn.Config(agent_app, host="127.0.0.1", port=agent_port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix="copilot-spring-") as tmpname:
        tmp = Path(tmpname)
        _wait_started(server)
        with _postgres(tmp) as (url, user, password):
            env = {
                **os.environ,
                "SPRING_PROFILES_ACTIVE": "local",
                "BACKEND_PORT": str(platform_port),
                "COPILOT_PLATFORM_TOKEN_KEY": PLATFORM_KEY.decode(),
                "COPILOT_SERVICE_TOKEN_KEY": SERVICE_KEY.decode(),
                "COPILOT_APPROVAL_KEY": APPROVAL_KEY,
                "COPILOT_AGENT_URL": f"http://127.0.0.1:{agent_port}",
                "COPILOT_DEV_TOKEN_ENABLED": "true",
                "SPRING_DATASOURCE_URL": url,
                "SPRING_DATASOURCE_USERNAME": user,
                "SPRING_DATASOURCE_PASSWORD": password,
            }
            log = (tmp / "spring.log").open("w")
            proc = subprocess.Popen(
                ["java", "-jar", str(jar)], env=env, stdout=log, stderr=subprocess.STDOUT
            )
            try:
                _wait(f"http://127.0.0.1:{platform_port}/api/v1/health", 90, "Spring backend")
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{platform_port}", timeout=60
                ) as client:
                    yield client, harness
            except RuntimeError:
                log.flush()
                print((tmp / "spring.log").read_text()[-4000:])
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log.close()
    server.should_exit = True
    thread.join(timeout=10)


def _wait_started(server: uvicorn.Server) -> None:
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("agent service did not start")
        time.sleep(0.05)
