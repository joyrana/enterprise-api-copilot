"""
Enterprise API Copilot — API Executor MCP Skill

Executes HTTP API calls with proper authentication headers.
Receives a fully-resolved API spec, parameters, and auth token.
Returns the full HTTP response.

MCP Tool Name: api_execute
Input:  { "method", "url", "headers", "body", "timeout_seconds" }
Output: { "status_code", "headers", "body", "duration_ms" }

TODO(#150): Implement URL allow-list validation (security).
TODO(#151): Add request/response size limits.
TODO(#152): Add support for multipart/form-data.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel, HttpUrl

logger = logging.getLogger(__name__)

app = Server("api-executor")


class ApiExecuteInput(BaseModel):
    """Input schema for the api_execute tool."""

    method: str
    url: str  # TODO: Change to HttpUrl after allow-list validation is in place
    headers: dict[str, str] = {}
    body: dict[str, Any] | str | None = None
    timeout_seconds: int = 30


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="api_execute",
            description=(
                "Execute an HTTP API call. Supports GET, POST, PUT, PATCH, DELETE. "
                "Returns the full response including status code, headers, and body."
            ),
            inputSchema=ApiExecuteInput.model_json_schema(),
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "api_execute":
        raise ValueError(f"Unknown tool: {name}")

    req = ApiExecuteInput(**arguments)

    # TODO(#150): Validate URL against allow-list
    # validate_allowed_host(req.url)

    logger.info("Executing API: %s %s", req.method, req.url)

    start_time = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=req.timeout_seconds) as client:
            response = await client.request(
                method=req.method.upper(),
                url=req.url,
                headers=req.headers,
                json=req.body if isinstance(req.body, dict) else None,
                content=req.body if isinstance(req.body, str) else None,
            )

        duration_ms = int((time.monotonic() - start_time) * 1000)

        try:
            response_body = response.json()
        except Exception:
            response_body = response.text

        result = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response_body,
            "duration_ms": duration_ms,
        }

        logger.info("API response: status=%d duration_ms=%d", response.status_code, duration_ms)

    except httpx.TimeoutException:
        result = {
            "error": "TIMEOUT",
            "message": f"Request timed out after {req.timeout_seconds}s",
        }
    except Exception as e:
        logger.exception("Unexpected error during API execution")
        result = {
            "error": "EXECUTION_ERROR",
            "message": str(e),
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
