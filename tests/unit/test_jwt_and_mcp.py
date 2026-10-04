from __future__ import annotations

import json
import time

import jwt
from mcp.client import Client

from skills.jwt.inspect import build_jwt_skill
from skills.mcp_server import META_APPROVAL, META_IDEMPOTENCY, create_mcp_server
from skills.runtime.contracts import Principal
from skills.runtime.errors import SkillErrorCode
from tests.support import build_harness

NOW = 1_800_000_000


def _token(**claims: object) -> str:
    return jwt.encode(
        claims,
        "unit-test-secret-not-real-0123456789abcdef",
        algorithm="HS256",
        headers={"kid": "k1"},
    )


async def test_jwt_inspection_reports_expiry_scopes_and_never_echoes() -> None:
    h = build_harness()
    now = int(time.time())
    token = _token(
        sub="user-12345",
        iss="https://idp.example",
        exp=now - 10,
        iat=now - 3610,
        scope="payments:read",
    )
    res = await h.services.runtime.invoke(
        "token.inspect",
        {"token": f"Bearer {token}", "required_scopes": ["payments:write"]},
        h.ctx(),
    )
    assert res.ok and res.output
    out = res.output
    assert out["expired"] is True and out["signature_verified"] is False
    assert out["missing_scopes"] == ["payments:write"]
    assert any("403" in issue for issue in out["issues"]) and any(
        "401" in issue for issue in out["issues"]
    )
    assert out["masked_claims"]["sub"] == "us***45"
    dumped = json.dumps(out)
    assert token not in dumped and token.split(".")[2] not in dumped
    assert all(token not in e.model_dump_json() for e in h.audit.events)  # audit redacts the input


async def test_jwt_alg_none_and_garbage() -> None:
    h = build_harness()
    unsigned = jwt.encode({"sub": "x"}, None, algorithm="none")
    res = await h.services.runtime.invoke("token.inspect", {"token": unsigned}, h.ctx())
    assert res.ok and res.output and any("alg 'none'" in i for i in res.output["issues"])
    assert any("no 'exp'" in i for i in res.output["issues"])
    bad = await h.services.runtime.invoke("token.inspect", {"token": "not-a-jwt-at-all"}, h.ctx())
    assert bad.error and bad.error.code is SkillErrorCode.INVALID_INPUT


async def test_mcp_lists_contract_schemas_and_routes_through_runtime() -> None:
    h = build_harness()
    server = create_mcp_server(
        h.services.runtime,
        principal=Principal(subject="alice", tenant_id="acme", roles=frozenset({"developer"})),
        environment="sandbox",
    )
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {
            "api.search",
            "api.call.write",
            "api.call.delete",
            "docs.search",
            "token.inspect",
        } <= set(tools)
        write = tools["api.call.write"]
        assert (
            write.annotations
            and write.annotations.destructive_hint is False
            and write.annotations.read_only_hint is False
        )
        assert tools["api.call.delete"].annotations.destructive_hint is True  # type: ignore[union-attr]
        assert write.input_schema["properties"]["operation_id"]["type"] == "string"

        ok = await client.call_tool("api.search", {"query": "refund a payment"})
        assert not ok.is_error and ok.structured_content
        assert ok.structured_content["results"][0]["operation_id"] == "refundPayment"

        body = {
            "operation_id": "createPayment",
            "body": {"amount": 10000, "currency": "INR", "customer_id": "cust_acm0001"},
        }
        denied = await client.call_tool("api.call.write", body, meta={META_IDEMPOTENCY: "mcp-1"})  # type: ignore[arg-type]
        assert denied.is_error
        payload = json.loads(denied.content[0].text)  # type: ignore[union-attr]
        assert payload["error"]["code"] == "APPROVAL_REQUIRED"

        # A forged approval passed through MCP metadata is rejected by the runtime.
        forged = await client.call_tool(
            "api.call.write",
            body,
            meta={META_IDEMPOTENCY: "mcp-1", META_APPROVAL: "v1.e30.AAAA"},  # type: ignore[arg-type]
        )
        assert json.loads(forged.content[0].text)["error"]["code"] == "APPROVAL_INVALID"  # type: ignore[union-attr]
    assert len(h.app.state.sandbox.tenant("acme").payments) == 3


async def test_mcp_principal_comes_from_server_config_not_arguments() -> None:
    h = build_harness()
    server = create_mcp_server(
        h.services.runtime,
        principal=Principal(subject="vic", tenant_id="acme", roles=frozenset({"viewer"})),
        environment="sandbox",
    )
    async with Client(server) as client:
        res = await client.call_tool(
            "api.call.read", {"operation_id": "listPayments", "principal": {"roles": ["admin"]}}
        )
        assert res.is_error
        assert json.loads(res.content[0].text)["error"]["code"] in {"INVALID_INPUT", "FORBIDDEN"}  # type: ignore[union-attr]
        res2 = await client.call_tool("api.call.read", {"operation_id": "listPayments"})
        assert json.loads(res2.content[0].text)["error"]["code"] == "FORBIDDEN"  # type: ignore[union-attr]


async def test_jwt_clock_injection_for_not_yet_valid() -> None:
    skill = build_jwt_skill(clock=lambda: NOW)
    h = build_harness()
    out = await skill.handler(
        skill.input_model(token=_token(nbf=NOW + 600, exp=NOW + 4000, iat=NOW)), h.ctx()
    )
    assert out.not_yet_valid and out.expired is False and out.lifetime_s == 4000
