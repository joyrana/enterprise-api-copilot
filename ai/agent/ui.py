"""Component registry for generative UI.

The response model decides *which* components the web app shows, and from which step;
the server builds every component's props from that step's real output. A model can
therefore choose layout but cannot put text or values on screen that no skill produced.

* Data components (``sources`` non-empty) render one step's output.
* ``run_trace`` (no source) shows the steps the agent took.
* ``approval_request`` and ``clarification`` are safety-relevant: the server always adds
  them when the run is paused, and a model can neither select nor suppress them.

The web app has a matching registry (``apps/frontend/src/components/genui``). Prop keys
avoid secret-looking names, because the public run view redacts those.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ai.agent.contracts import RunState, RunStatus, UIComponent

MAX_COMPONENTS = 5
_MAX_BODY_CHARS = 6000

Props = dict[str, Any]


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    description: str
    sources: frozenset[str]  # skill ids whose output the component renders
    build: Callable[[dict[str, Any]], Props]
    selectable: bool = True  # False: server-controlled (approval, clarification)


def _operation_list(out: dict[str, Any]) -> Props:
    return {
        "operations": [
            {
                k: hit.get(k)
                for k in (
                    "operation_id",
                    "api",
                    "method",
                    "path",
                    "summary",
                    "scopes",
                    "invocation_skill",
                )
            }
            for hit in out.get("results", [])
        ]
    }


def _operation_detail(out: dict[str, Any]) -> Props:
    schema = out.get("request_body_schema") or {}
    required = set(schema.get("required", []))
    return {
        "operation_id": out["operation_id"],
        "api_title": out.get("api_title"),
        "api_version": out.get("api_version"),
        "method": out.get("method"),
        "path": out.get("path"),
        "summary": out.get("summary"),
        "description": out.get("description"),
        "authentication": out.get("authentication"),
        "scopes": out.get("required_scopes", []),
        "side_effect": out.get("side_effect"),
        "deprecated": out.get("deprecated", False),
        "parameters": [
            {
                "name": p["name"],
                "location": p["location"],
                "required": p["required"],
                "description": p.get("description", ""),
            }
            for p in out.get("parameters", [])
        ],
        "body_required": out.get("request_body_required", False),
        "body_fields": [
            {
                "name": name,
                "type": (prop or {}).get("type"),
                "required": name in required,
                "description": (prop or {}).get("description", ""),
                "enum": (prop or {}).get("enum"),
            }
            for name, prop in schema.get("properties", {}).items()
        ],
        "responses": out.get("responses", {}),
    }


def _code_snippets(out: dict[str, Any]) -> Props:
    return {
        "operation_id": out["operation_id"],
        "snippets": out.get("snippets", {}),
        "notes": out.get("notes", []),
    }


def _api_response(out: dict[str, Any]) -> Props:
    body = out.get("response_body")
    text = json.dumps(body, indent=2, default=str) if body is not None else ""
    return {
        "operation_id": out.get("operation_id"),
        "method": out.get("method"),
        "path": out.get("path"),
        "status_code": out.get("status_code"),
        "ok": out.get("ok"),
        "correlation_id": out.get("correlation_id"),
        "retry_after_s": out.get("retry_after_s"),
        "response_body": body if len(text) <= _MAX_BODY_CHARS else None,
        "response_preview": text[:_MAX_BODY_CHARS] if len(text) > _MAX_BODY_CHARS else None,
        "curl": out.get("curl"),
    }


def _doc_answer(out: dict[str, Any]) -> Props:
    answer = out.get("answer") or {}
    return {
        "extract": answer.get("text", ""),
        "abstained": answer.get("abstained", False),
        "citations": answer.get("citations", []),
        "sources": [
            {k: s.get(k) for k in ("source_id", "title", "section", "uri", "flagged")}
            for s in out.get("sources", [])
        ],
    }


def _jwt_report(out: dict[str, Any]) -> Props:
    return {
        "algorithm": out.get("algorithm"),
        "key_id": out.get("key_id"),
        "kind": out.get("token_type"),
        "scopes": out.get("scopes", []),
        "missing_scopes": out.get("missing_scopes", []),
        "expires_at": out.get("expires_at"),
        "issued_at": out.get("issued_at"),
        "expired": out.get("expired"),
        "lifetime_s": out.get("lifetime_s"),
        "claims": out.get("masked_claims", {}),
        "issues": out.get("issues", []),
        "verified": out.get("signature_verified", False),
        "note": out.get("note"),
    }


REGISTRY: dict[str, ComponentSpec] = {
    spec.name: spec
    for spec in (
        ComponentSpec(
            "operation_list",
            "Table of API operations found by a search (method, path, summary, scopes).",
            frozenset({"api.search"}),
            _operation_list,
        ),
        ComponentSpec(
            "operation_detail",
            "Full contract of one operation: auth, scopes, parameters, body fields, responses.",
            frozenset({"api.describe"}),
            _operation_detail,
        ),
        ComponentSpec(
            "code_snippets",
            "Tabbed code samples (cURL, Python, JavaScript, Java) for an operation.",
            frozenset({"code.generate"}),
            _code_snippets,
        ),
        ComponentSpec(
            "api_response",
            "Result of an executed API call: HTTP status, response JSON, correlation id, cURL.",
            frozenset({"api.call.read", "api.call.write", "api.call.delete"}),
            _api_response,
        ),
        ComponentSpec(
            "doc_sources",
            "Documentation passages and citations that back the answer.",
            frozenset({"docs.search"}),
            _doc_answer,
        ),
        ComponentSpec(
            "jwt_report",
            "Decoded JWT: algorithm, expiry, scopes, masked claims and detected problems.",
            frozenset({"token.inspect"}),
            _jwt_report,
        ),
        ComponentSpec(
            "run_trace",
            "Timeline of the skills the agent called to produce this answer.",
            frozenset(),
            lambda _out: {},
        ),
        ComponentSpec(
            "approval_request",
            "Approve or reject a pending side-effecting action (server-controlled).",
            frozenset(),
            lambda _out: {},
            selectable=False,
        ),
        ComponentSpec(
            "clarification",
            "Ask the user for missing required values (server-controlled).",
            frozenset(),
            lambda _out: {},
            selectable=False,
        ),
    )
}


def selectable_components() -> list[ComponentSpec]:
    return [spec for spec in REGISTRY.values() if spec.selectable]


def catalog_for_prompt() -> str:
    lines = []
    for spec in selectable_components():
        source = (
            f"source: a step that ran {', '.join(sorted(spec.sources))}"
            if spec.sources
            else 'source: ""'
        )
        lines.append(f"- {spec.name}: {spec.description} ({source})")
    return "\n".join(lines)


def _trace_props(state: RunState) -> Props:
    steps = []
    for step in state.plan.steps if state.plan else []:
        result = state.results.get(step.step_id)
        steps.append(
            {
                "step_id": step.step_id,
                "skill_id": state.resolved_skills.get(step.step_id, step.skill_id),
                "purpose": step.purpose,
                "ok": result.ok if result else None,
                "duration_ms": result.duration_ms if result else None,
            }
        )
    return {"steps": steps, "mode": state.mode}


def build_components(
    state: RunState, choices: list[tuple[str, str]] | None
) -> tuple[list[UIComponent], list[str]]:
    """Validate the model's ``(component, source_step)`` choices and build props.

    ``choices=None`` selects the default layout (one data component per successful step).
    Returns the components and the human-readable reasons any choice was rejected.
    """
    ok_steps = {
        step_id: result
        for step_id, result in state.results.items()
        if result.ok and result.output is not None
    }
    if choices is None:
        choices = []
        for step_id, result in ok_steps.items():
            spec = next(
                (s for s in REGISTRY.values() if result.skill_id in s.sources and s.selectable),
                None,
            )
            if spec is not None:
                choices.append((spec.name, step_id))
    out: list[UIComponent] = []
    rejected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for name, source in choices:
        spec = REGISTRY.get(name)
        if spec is None or not spec.selectable:
            rejected.append(f"{name}: not a selectable component")
            continue
        key = (name, source if spec.sources else "")
        if key in seen:
            continue
        if spec.sources:
            chosen = ok_steps.get(source)
            if chosen is None or chosen.skill_id not in spec.sources:
                rejected.append(
                    f"{name}: '{source}' is not a successful {'/'.join(spec.sources)} step"
                )
                continue
            props = spec.build(chosen.output or {})
        else:
            if name == "run_trace" and not (state.plan and state.plan.steps):
                continue
            props = _trace_props(state)
        seen.add(key)
        out.append(
            UIComponent(
                id=f"ui{len(out) + 1}",
                component=name,
                source=source if spec.sources else None,
                props=props,
            )
        )
        if len(out) >= MAX_COMPONENTS:
            break
    if state.status is RunStatus.AWAITING_APPROVAL and state.pending_approval is not None:
        out.append(
            UIComponent(
                id="approval",
                component="approval_request",
                source=state.pending_approval.step_id,
                props={
                    "summary": state.pending_approval.summary,
                    "action_hash": state.pending_approval.action_hash,
                    "skill_id": state.pending_approval.skill_id,
                    "environment": state.pending_approval.environment,
                    "arguments": state.pending_approval.arguments,
                },
            )
        )
    if state.status is RunStatus.NEEDS_CLARIFICATION:
        out.append(
            UIComponent(
                id="clarification",
                component="clarification",
                props={
                    "question": state.message,
                    "missing_fields": state.missing_fields,
                },
            )
        )
    return out, rejected
