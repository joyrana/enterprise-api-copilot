"""MCP adapter over the skill runtime (ADR-0006).

* ``tools/list`` is generated from the registry: input/output schemas come from the
  skill contracts; MCP annotations mirror side-effect classes (hints only).
* ``tools/call`` always goes through ``SkillRuntime.invoke``. There is no other path.
* The principal and environment are fixed by whoever launches the server (configuration),
  never by tool arguments. Approval tokens and idempotency keys travel in request
  ``_meta`` under ``io.copilot/approval_token`` and ``io.copilot/idempotency_key``.
* Skill failures are returned as ``is_error`` results carrying the typed error, so MCP
  clients see the same contract as the agent.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import mcp.types as types
from mcp.server import Server

from skills.runtime.contracts import InvocationContext, Principal, SideEffect
from skills.runtime.runtime import SkillRuntime

META_APPROVAL = "io.copilot/approval_token"
META_IDEMPOTENCY = "io.copilot/idempotency_key"
SERVER_NAME = "enterprise-api-copilot-skills"


def _annotations(side_effect: SideEffect) -> types.ToolAnnotations:
    return types.ToolAnnotations(
        read_only_hint=side_effect in (SideEffect.NONE, SideEffect.READ),
        destructive_hint=side_effect is SideEffect.DESTRUCTIVE,
        idempotent_hint=side_effect in (SideEffect.NONE, SideEffect.READ),
        open_world_hint=side_effect is not SideEffect.NONE,
    )


def _meta_value(params: types.CallToolRequestParams, key: str) -> str | None:
    meta = params.meta
    if meta is None:
        return None
    value = dict(meta).get(key)  # RequestParamsMeta is a dict subtype in MCP SDK 2.x
    return str(value) if isinstance(value, str) and value else None


def create_mcp_server(
    runtime: SkillRuntime, *, principal: Principal, environment: str
) -> Server[Any]:
    async def list_tools(
        ctx: Any, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = []
        for d in runtime.registry.descriptors():
            tools.append(
                types.Tool(
                    name=d.id,
                    title=d.name,
                    description=(
                        f"{d.description} [side effect: {d.side_effect.value}; "
                        f"requires approval: {str(d.requires_approval).lower()}]"
                    ),
                    input_schema=d.input_schema,
                    output_schema=d.output_schema,
                    annotations=_annotations(d.side_effect),
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        invocation = InvocationContext(
            principal=principal,
            environment=environment,
            correlation_id=f"mcp_{uuid.uuid4().hex[:16]}",
            approval_token=_meta_value(params, META_APPROVAL),
            idempotency_key=_meta_value(params, META_IDEMPOTENCY),
        )
        result = await runtime.invoke(params.name, dict(params.arguments or {}), invocation)
        if result.ok and result.output is not None:
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=json.dumps(result.output, default=str))
                ],
                structured_content=result.output,
                is_error=False,
            )
        error = result.error.model_dump(mode="json") if result.error else {"code": "INTERNAL_ERROR"}
        payload = {
            "error": error,
            "action_hash": result.action_hash,
            "correlation_id": result.correlation_id,
        }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, default=str))],
            is_error=True,
        )

    return Server(SERVER_NAME, version="0.2.0", on_list_tools=list_tools, on_call_tool=call_tool)
