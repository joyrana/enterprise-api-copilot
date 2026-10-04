"""Run the synthetic sandbox gateway locally.

    python -m sandbox --port 8090

Client secrets are generated per start-up and printed once to stderr so they can be put
in a local ``.env`` (development only — never reuse them anywhere else). Set
``SANDBOX_CLIENT_SECRET`` to pin the secret of ``acme-sandbox-app`` across restarts.
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from sandbox.app import SandboxConfig, create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m sandbox")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--no-faults", action="store_true", help="disable X-Sandbox-Fault injection"
    )
    args = parser.parse_args(argv)

    config = SandboxConfig.default()
    config.fault_injection = not args.no_faults
    pinned = os.environ.get("SANDBOX_CLIENT_SECRET")
    if pinned:
        config.clients["acme-sandbox-app"].client_secret = pinned
    print("Synthetic sandbox clients (development only):", file=sys.stderr)
    for client in config.clients.values():
        print(
            f"  {client.client_id} tenant={client.tenant_id} secret={client.client_secret}",
            file=sys.stderr,
        )
    uvicorn.run(create_app(config), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
