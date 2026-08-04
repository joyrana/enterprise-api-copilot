"""Compatibility shim for legacy `skills/sdk-generator/server.py` entrypoint."""

from skills.api.sdk_generator.server import app, main

__all__ = ["app", "main"]

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
