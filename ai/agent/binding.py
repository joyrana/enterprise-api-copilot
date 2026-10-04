"""Deterministic argument binding from extracted entities to an operation's contract.

Only values the user actually supplied (parsed entities) are bound. Required fields that
cannot be bound are reported as missing so the run asks for clarification instead of
guessing — the model never invents identifiers or amounts. Text from retrieved documents
is never a source of arguments (threat model T1).
"""

from __future__ import annotations

from typing import Any

from ai.agent.contracts import Entities

_ENTITY_FIELDS = {
    "payment_id": "payment_id",
    "customer_id": "customer_id",
    "order_id": "order_id",
    "amount": "amount_minor",
    "currency": "currency",
    "status": "status_filter",
    "reason": "refund_reason",
}


def _entity(entities: Entities, field: str) -> Any:
    attr = _ENTITY_FIELDS.get(field)
    return getattr(entities, attr) if attr else None


def bind_call_arguments(
    describe: dict[str, Any], entities: Entities
) -> tuple[dict[str, Any], list[str]]:
    args: dict[str, Any] = {"operation_id": describe["operation_id"]}
    missing: list[str] = []
    path_params: dict[str, str] = {}
    query: dict[str, Any] = {}
    for param in describe.get("parameters", []):
        value = _entity(entities, param["name"])
        if param["location"] == "path":
            if value is None:
                missing.append(f"path.{param['name']}")
            else:
                path_params[param["name"]] = str(value)
        elif param["location"] == "query" and value is not None:
            allowed = (param.get("schema") or {}).get("enum")
            if allowed is None or value in allowed:
                query[param["name"]] = value
    if path_params:
        args["path_params"] = path_params
    if query:
        args["query"] = query

    schema = describe.get("request_body_schema")
    if schema:
        body: dict[str, Any] = {}
        properties = schema.get("properties", {})
        for name, prop in properties.items():
            value = _entity(entities, name)
            if value is None:
                continue
            allowed = (prop or {}).get("enum")
            if allowed is not None and value not in allowed:
                continue
            body[name] = value
        for name in schema.get("required", []):
            if name not in body:
                missing.append(f"body.{name}")
        if body or describe.get("request_body_required"):
            args["body"] = body
    return args, missing
