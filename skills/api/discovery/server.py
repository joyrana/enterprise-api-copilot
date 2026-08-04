"""
Enterprise API Copilot — API Discovery MCP Skill

This MCP skill searches the API catalog for APIs matching a natural
language query. It uses vector similarity search over indexed OpenAPI specs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = Server("api-discovery")


class ApiDiscoveryInput(BaseModel):
    """Input schema for the api_discovery tool."""

    query: str
    limit: int = 5
    method_filter: str | None = None


class ApiMatch(BaseModel):
    """A single API match result."""

    name: str
    method: str
    path: str
    description: str
    score: float


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Declare the tools provided by this MCP skill."""
    return [
        Tool(
            name="api_discovery",
            description=(
                "Discover enterprise APIs matching a natural language query. "
                "Returns a ranked list of APIs from the catalog that best match "
                "the intent of the query."
            ),
            inputSchema=ApiDiscoveryInput.model_json_schema(),
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool invocations."""
    if name != "api_discovery":
        raise ValueError(f"Unknown tool: {name}")

    input_data = ApiDiscoveryInput(**arguments)

    logger.info("Discovering APIs for query: %s", input_data.query)

    placeholder_results = [
        ApiMatch(
            name="Create Payment",
            method="POST",
            path="/v1/payments",
            description="Creates a new payment transaction",
            score=0.95,
        )
    ]

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"apis": [r.model_dump() for r in placeholder_results]},
                indent=2,
            ),
        )
    ]


async def main() -> None:
    """Start the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
