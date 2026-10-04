from __future__ import annotations

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

from ai.knowledge.openapi import MAX_SPEC_BYTES, SpecError, load_spec
from skills.api import codegen
from skills.api.gateway import expand_path
from skills.runtime.errors import SkillError

SPEC = Path(__file__).resolve().parents[2] / "sandbox" / "specs" / "payments-v1.yaml"


def test_payments_spec_parses_with_refs_and_scopes() -> None:
    spec = load_spec(SPEC.read_text(), api_id="payments-v1")
    ops = {o.operation_id: o for o in spec.operations}
    assert set(ops) == {
        "listPayments",
        "createPayment",
        "getPayment",
        "cancelPayment",
        "refundPayment",
        "listCustomers",
        "getCustomer",
    }
    create = ops["createPayment"]
    assert create.scopes == ["payments:write"] and create.requires_idempotency_key
    assert create.request_body_schema and create.request_body_schema["properties"]["currency"][
        "enum"
    ] == ["INR", "USD", "EUR"]
    assert ops["getPayment"].parameters[0].name == "payment_id"  # path-level parameter inherited
    assert ops["listPayments"].scopes == ["payments:read"]
    assert spec.declared_servers == ["https://payments.sandbox.example.invalid"]


def test_hostile_specs_rejected_or_contained() -> None:
    with pytest.raises(SpecError):
        load_spec("swagger: '2.0'", api_id="x")
    with pytest.raises(SpecError):
        load_spec("a" * (MAX_SPEC_BYTES + 1), api_id="x")
    cyclic = {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/n": {
                "post": {
                    "operationId": "n",
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/components/schemas/Node"}},
                }
            }
        },
    }
    op = load_spec(cyclic, api_id="c").operations[0]
    assert "x-unresolved" in str(op.request_body_schema)  # cycle bounded, not infinite
    external = {
        **cyclic,
        "paths": {
            "/e": {
                "get": {"operationId": "e", "parameters": [{"$ref": "https://evil.example/p.yaml"}]}
            }
        },
    }
    assert load_spec(external, api_id="e").operations[0].parameters[0].name == ""  # not fetched


def test_path_expansion_encodes_and_rejects_traversal() -> None:
    assert expand_path("/v1/payments/{id}", {"id": "a/b c"}) == "/v1/payments/a%2Fb%20c"
    for bad in ({"id": ".."}, {"other": "x"}, {}):
        with pytest.raises(SkillError):
            expand_path("/v1/payments/{id}", bad)


BODY = {
    "amount": 50000,
    "currency": "INR",
    "customer_id": "cust_acm0001",
    "description": 'it\'s "quoted" $(rm -rf /)',
}


def _snippets() -> dict[str, str]:
    return codegen.render(
        method="POST",
        base_url="https://api.example.com",
        path="/v1/payments",
        query={"expand": True},
        body=BODY,
        headers={
            "Idempotency-Key": "k1",
            "Authorization": "Bearer SECRET-SHOULD-NOT-APPEAR",
            "Cookie": "s=1",
        },
    )


def test_snippets_never_contain_credentials() -> None:
    for lang, text in _snippets().items():
        assert "SECRET-SHOULD-NOT-APPEAR" not in text and "Cookie" not in text, lang
        assert "COPILOT_TOKEN" in text, lang


def test_curl_quoting_prevents_shell_injection() -> None:
    curl = _snippets()["curl"]
    assert "--data '" in curl and "$(rm -rf /)" in curl
    assert "'\"'\"'" in curl  # embedded single quote escaped shlex-style


def test_python_snippet_is_valid_python() -> None:
    ast.parse(_snippets()["python"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_javascript_snippet_is_valid_javascript(tmp_path: Path) -> None:
    src = tmp_path / "s.mjs"
    src.write_text(_snippets()["javascript"])
    assert (
        subprocess.run(["node", "--check", str(src)], capture_output=True, check=False).returncode
        == 0
    )


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
def test_java_snippet_compiles(tmp_path: Path) -> None:
    snippet = _snippets()["java"]
    imports = "".join(line + "\n" for line in snippet.splitlines() if line.startswith("import "))
    body = "\n".join(line for line in snippet.splitlines() if not line.startswith("import "))
    (tmp_path / "Snippet.java").write_text(
        f"{imports}\npublic class Snippet "
        f"{{\n  public static void main(String[] a) throws Exception {{\n{body}\n  }}\n}}\n"
    )
    proc = subprocess.run(
        ["javac", "-d", str(tmp_path), str(tmp_path / "Snippet.java")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


async def test_codegen_without_body_or_ids_uses_marked_placeholders() -> None:
    from tests.support import build_harness

    h = build_harness()
    res = await h.services.runtime.invoke(
        "code.generate", {"operation_id": "createOrder", "languages": ["curl"]}, h.ctx()
    )
    assert res.ok and res.output
    assert '"items":[{"sku":"<string>","quantity":1}]' in res.output["snippets"]["curl"]
    assert any("placeholder" in n for n in res.output["notes"])
    res = await h.services.runtime.invoke(
        "code.generate", {"operation_id": "getPayment", "languages": ["curl"]}, h.ctx()
    )
    assert res.ok and res.output and "/v1/payments/<payment_id>" in res.output["snippets"]["curl"]
    bad = await h.services.runtime.invoke(
        "code.generate", {"operation_id": "getPayment", "path_params": {"payment_id": "x"}}, h.ctx()
    )
    assert bad.error is not None  # supplied values are still validated against the spec
