"""
Enterprise API Copilot — JWT MCP Skill

Obtains and caches JWT tokens from Apigee using client credentials flow.
Used by the executor skill to authenticate outbound API calls.

MCP Tool Name: get_token
Input:  { "env": "sandbox|staging|production", "scopes": ["payments:write"] }
Output: { "access_token", "token_type", "expires_in", "scope" }

TODO(#160): Implement Apigee client credentials OAuth 2.0 flow.
TODO(#161): Add token caching with TTL (avoid re-fetching on every call).
TODO(#162): Add support for per-API scopes.
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

app = Server("jwt")


class GetTokenInput(BaseModel):
    """Input schema for the get_token tool."""

    env: str = "sandbox"
    scopes: list[str] = []


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_token",
            description=(
                "Obtain a JWT access token from Apigee for authenticating API calls. "
                "Uses client credentials OAuth 2.0 flow. Tokens are cached until expiry."
            ),
            inputSchema=GetTokenInput.model_json_schema(),
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "get_token":
        raise ValueError(f"Unknown tool: {name}")

    req = GetTokenInput(**arguments)

    logger.info("Obtaining token for env=%s scopes=%s", req.env, req.scopes)

    # TODO(#160): Implement real Apigee OAuth flow
    # token = await apigee_client.get_token(env=req.env, scopes=req.scopes)

    # Placeholder response
    result = {
        "access_token": "PLACEHOLDER_TOKEN_NOT_IMPLEMENTED",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": " ".join(req.scopes),
        "warning": "JWT skill not yet implemented. See issue #160.",
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
