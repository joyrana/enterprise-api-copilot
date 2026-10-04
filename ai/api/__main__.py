"""Serve the APIs.

    python -m ai.api platform --port 8080   # local reference platform API (local mode only)
    python -m ai.api agent --port 8000      # internal agent-service API

Configuration comes from the environment (``.env.example``). The agent API needs
``COPILOT_SERVICE_TOKEN_KEY`` (≥32 bytes) shared with the platform; in local mode a random
key is generated and printed once to stderr if it is missing.
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys

import uvicorn

from ai.api.agent_app import create_agent_app
from ai.api.platform_app import PlatformConfig, create_platform_app
from ai.bootstrap import Settings, build_services


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m ai.api")
    parser.add_argument("service", choices=["platform", "agent"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    os.environ.setdefault("COPILOT_STATE_DB", ".copilot/state.db")
    settings = Settings.from_env()
    services = build_services(settings)
    if args.service == "platform":
        app = create_platform_app(services, PlatformConfig.from_env())
        port = args.port or 8080
    else:
        key = os.environ.get("COPILOT_SERVICE_TOKEN_KEY", "").encode()
        if not key:
            if settings.runtime_mode not in {"local", "test"}:
                raise SystemExit("COPILOT_SERVICE_TOKEN_KEY is required outside local/test mode")
            generated = secrets.token_urlsafe(48)
            print(f"dev-only COPILOT_SERVICE_TOKEN_KEY={generated}", file=sys.stderr)
            key = generated.encode()
        if services.state is None:
            raise SystemExit("COPILOT_STATE_DB is required for the agent service (durable runs)")
        app = create_agent_app(services, service_key=key, store=services.state)
        port = args.port or 8000
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
