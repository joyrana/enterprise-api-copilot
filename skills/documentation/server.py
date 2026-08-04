"""Compatibility shim for legacy `skills/documentation/server.py` entrypoint."""

from skills.docs.server import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
