"""Grounding: model-proposed values are only used when the user actually supplied them.

The model decides *what* to do; it is never a source of identifiers, amounts or other
argument values (threat model T1). Every value the model extracts or proposes is checked
against the user's own text and the deterministic entity parse:

* identifiers and free text must appear verbatim in the request;
* numbers must appear in the request, or equal the parsed amount; an ``amount`` field
  always takes the deterministically parsed minor-unit amount when one exists;
* enum values must be allowed by the schema *and* be mentioned (or parsed) — a model
  default such as ``"INR"`` for an unmentioned currency is not grounded.

Ungrounded values are dropped. Required fields that remain unbound are reported as
missing, so the run asks the user instead of guessing. Text from documents or API
responses is never a grounding source.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ai.agent.binding import bind_call_arguments
from ai.agent.contracts import Entities
from ai.agent.intent import currency_mentions

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LANGUAGES = {"curl", "python", "javascript", "java"}
_REFUND_REASONS = {"duplicate", "fraudulent", "requested_by_customer"}
_STATUS_WORDS = {"authorized", "captured", "refunded", "cancelled"}


class GroundedCall(BaseModel):
    arguments: dict[str, Any]
    missing: list[str] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)  # model-proposed, ungrounded
    overridden: list[str] = Field(default_factory=list)  # replaced by the parsed value


def _numbers(query: str) -> set[float]:
    return {float(n.replace(",", "")) for n in _NUMBER.findall(query)}


def _entity_values(entities: Entities) -> set[str]:
    values = {
        entities.payment_id,
        entities.customer_id,
        entities.order_id,
        entities.currency,
        entities.status_filter,
        entities.refund_reason,
    }
    return {v for v in values if v}


def is_grounded(value: Any, schema: dict[str, Any], query: str, entities: Entities) -> bool:
    if isinstance(value, bool):
        return False
    lowered = query.lower()
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        return False
    if isinstance(value, int | float):
        return value == entities.amount_minor or float(value) in _numbers(query)
    if not isinstance(value, str) or not value.strip():
        return False
    if value in _entity_values(entities) or value in currency_mentions(query):
        return True
    return value.lower() in lowered


def ground_entities(
    candidate: Entities, query: str, reference: Entities
) -> tuple[Entities, list[str]]:
    """Merge model-extracted entities into the deterministic parse, keeping grounded ones.

    The deterministic parse wins wherever it found a value (patterns are exact); the model
    fills gaps only with values that appear in the request.
    """
    out = reference.model_copy(deep=True)
    dropped: list[str] = []

    def take(field: str, ok: bool) -> None:
        value = getattr(candidate, field)
        if value in (None, []) or getattr(out, field) not in (None, []):
            return
        if ok:
            setattr(out, field, value)
        else:
            dropped.append(field)

    for field in ("payment_id", "customer_id", "order_id"):
        value = getattr(candidate, field)
        take(field, isinstance(value, str) and value in query)
    if candidate.amount_minor is not None:
        numbers = _numbers(query)
        take(
            "amount_minor",
            candidate.amount_minor in numbers or candidate.amount_minor / 100 in numbers,
        )
    take("currency", candidate.currency in currency_mentions(query))
    take(
        "status_filter",
        candidate.status_filter in _STATUS_WORDS and str(candidate.status_filter) in query.lower(),
    )
    take("refund_reason", candidate.refund_reason in _REFUND_REASONS)
    if candidate.status_codes and not out.status_codes:
        grounded = [c for c in candidate.status_codes if str(c) in query]
        out.status_codes = sorted(set(grounded))
        if len(grounded) < len(candidate.status_codes):
            dropped.append("status_codes")
    if candidate.languages and not out.languages:
        out.languages = sorted({lang for lang in candidate.languages if lang in _LANGUAGES})
    if candidate.operation_hint and not out.operation_hint:
        out.operation_hint = candidate.operation_hint[:120]
    return out, dropped


def ground_call_arguments(
    proposed: dict[str, Any], describe: dict[str, Any], query: str, entities: Entities
) -> GroundedCall:
    """Validate model-proposed ``api.call.*`` arguments against the described contract."""
    result = GroundedCall(arguments={"operation_id": describe["operation_id"]})
    fallback, _ = bind_call_arguments(describe, entities)

    def schema_of(param: dict[str, Any]) -> dict[str, Any]:
        return param.get("schema") or param.get("schema_") or {}

    path_params: dict[str, str] = {}
    query_params: dict[str, Any] = {}
    proposed_path = proposed.get("path_params") or {}
    proposed_query = proposed.get("query") or {}
    for param in describe.get("parameters", []):
        name, location = param["name"], param["location"]
        source = proposed_path if location == "path" else proposed_query
        if location not in ("path", "query"):
            continue
        value = source.get(name) if isinstance(source, dict) else None
        if value is not None and not is_grounded(value, schema_of(param), query, entities):
            result.dropped.append(f"{location}.{name}")
            value = None
        if value is None:
            value = (fallback.get("path_params" if location == "path" else "query") or {}).get(name)
        if location == "path":
            if value is None:
                result.missing.append(f"path.{name}")
            else:
                path_params[name] = str(value)
        elif value is not None:
            query_params[name] = value
    if path_params:
        result.arguments["path_params"] = path_params
    if query_params:
        result.arguments["query"] = query_params

    schema = describe.get("request_body_schema")
    if schema:
        properties: dict[str, Any] = schema.get("properties", {})
        proposed_body = proposed.get("body") if isinstance(proposed.get("body"), dict) else {}
        body: dict[str, Any] = {}
        for name, value in (proposed_body or {}).items():
            prop = properties.get(name)
            if prop is None or not is_grounded(value, prop or {}, query, entities):
                result.dropped.append(f"body.{name}")
                continue
            body[name] = value
        if entities.amount_minor is not None and "amount" in properties:
            if body.get("amount") not in (None, entities.amount_minor):
                result.overridden.append("body.amount")
            body["amount"] = entities.amount_minor
        for name, value in (fallback.get("body") or {}).items():
            body.setdefault(name, value)
        for name in schema.get("required", []):
            if name not in body:
                result.missing.append(f"body.{name}")
        if body or describe.get("request_body_required"):
            result.arguments["body"] = body
    return result
