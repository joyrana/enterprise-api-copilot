"""Compatibility shim for legacy `skills/api-executor/server.py` entrypoint."""

from skills.api.executor.server import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
