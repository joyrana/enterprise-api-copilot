"""Compatibility shim for legacy `skills/api-discovery/server.py` entrypoint."""

from skills.api.discovery.server import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
