"""
Enterprise API Copilot — SDK Generator MCP Skill

Generates equivalent curl commands and SDK code snippets from an
executed API call.
"""

from __future__ import annotations

import json
import logging
import shlex
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = Server("sdk-generator")


class GenerateSdkInput(BaseModel):
    """Input schema for the generate_sdk tool."""

    method: str
    url: str
    headers: dict[str, str] = {}
    body: dict[str, Any] | None = None


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_sdk",
            description=(
                "Generate curl and SDK code snippets for an API call. "
                "Supports curl, Java (Spring RestTemplate), Python (requests), "
                "and JavaScript (fetch)."
            ),
            inputSchema=GenerateSdkInput.model_json_schema(),
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "generate_sdk":
        raise ValueError(f"Unknown tool: {name}")

    req = GenerateSdkInput(**arguments)
    result = {
        "curl": _generate_curl(req),
        "python": _generate_python(req),
        "java": _generate_java(req),
        "javascript": _generate_javascript(req),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


def _generate_curl(req: GenerateSdkInput) -> str:
    parts = [f"curl -X {req.method.upper()}"]
    for k, v in req.headers.items():
        parts.append(f"  -H {shlex.quote(f'{k}: {v}')}")
    if req.body:
        parts.append("  -H 'Content-Type: application/json'")
        parts.append(f"  -d {shlex.quote(json.dumps(req.body))}")
    parts.append(f"  {shlex.quote(req.url)}")
    return " \\\n".join(parts)


def _generate_python(req: GenerateSdkInput) -> str:
    body_line = f"\njson={json.dumps(req.body, indent=4)}," if req.body else ""
    headers_repr = json.dumps(req.headers, indent=4) if req.headers else "{}"
    return f"""import requests

response = requests.{req.method.lower()}(
    url=\"{req.url}\",
    headers={headers_repr},{body_line}
)
print(response.status_code, response.json())
"""


def _generate_java(req: GenerateSdkInput) -> str:
    body_line = f'\n        entity = new HttpEntity<>({json.dumps(req.body)}, headers);' if req.body else ""
    return f"""// Spring RestTemplate
RestTemplate restTemplate = new RestTemplate();
HttpHeaders headers = new HttpHeaders();
{chr(10).join(f'headers.set(\"{k}\", \"{v}\");' for k, v in req.headers.items())}
HttpEntity<?> entity;{body_line}
ResponseEntity<String> response = restTemplate.exchange(
    \"{req.url}\",
    HttpMethod.{req.method.upper()},
    entity,
    String.class
);
System.out.println(response.getStatusCode() + \" \" + response.getBody());
"""


def _generate_javascript(req: GenerateSdkInput) -> str:
    body_part = f"\n  body: JSON.stringify({json.dumps(req.body)})," if req.body else ""
    headers_js = json.dumps(req.headers, indent=4) if req.headers else "{}"
    return f"""const response = await fetch(\"{req.url}\", {{
  method: \"{req.method.upper()}\",
  headers: {headers_js},{body_part}
}});
const data = await response.json();
console.log(response.status, data);
"""


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
