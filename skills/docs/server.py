"""Documentation skill placeholder until MCP wiring is finalized."""

from __future__ import annotations

app = None


async def main() -> None:
    """Placeholder entrypoint for the docs skill."""
    msg = "skills.docs.server is scaffolded but not yet wired to MCP runtime."
    raise NotImplementedError(msg)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
