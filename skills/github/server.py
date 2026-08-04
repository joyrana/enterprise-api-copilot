"""GitHub skill placeholder until MCP wiring is finalized."""

from __future__ import annotations

app = None


async def main() -> None:
    """Placeholder entrypoint for the github skill."""
    msg = "skills.github.server is scaffolded but not yet wired to MCP runtime."
    raise NotImplementedError(msg)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
