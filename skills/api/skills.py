"""API skills: search, describe, call (read / write / delete) and code generation.

Calls are split into three skills by HTTP method class so that the side-effect class, the
permission and the approval requirement are static properties of the skill rather than
something a model could influence through arguments.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field

from ai.knowledge.openapi import ApiOperation
from skills.api import codegen
from skills.api.catalog import ApiCatalog
from skills.api.gateway import ApiGateway, expand_path
from skills.runtime.contracts import InvocationContext, RetryPolicy, SideEffect, SkillDefinition
from skills.runtime.errors import SkillError, SkillErrorCode
from skills.runtime.policy import (
    API_INVOKE_DELETE,
    API_INVOKE_READ,
    API_INVOKE_WRITE,
    CATALOG_READ,
    CODE_GENERATE,
)
from skills.runtime.redaction import redact

MAX_RESPONSE_PREVIEW = 20_000
RETRYABLE_STATUS = frozenset({502, 503, 504})
METHOD_CLASS: dict[str, tuple[str, SideEffect]] = {
    "GET": ("api.call.read", SideEffect.READ),
    "HEAD": ("api.call.read", SideEffect.READ),
    "POST": ("api.call.write", SideEffect.WRITE),
    "PUT": ("api.call.write", SideEffect.WRITE),
    "PATCH": ("api.call.write", SideEffect.WRITE),
    "DELETE": ("api.call.delete", SideEffect.DESTRUCTIVE),
}

Scalar = str | int | float | bool


# ── search ────────────────────────────────────────────────────────────────────
class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    mode: Literal["keyword", "dense", "hybrid"] = "hybrid"


class SearchHit(BaseModel):
    operation_id: str
    api: str
    method: str
    path: str
    summary: str
    scopes: list[str]
    invocation_skill: str
    score: float
    rank: int
    source_id: str


class SearchOutput(BaseModel):
    results: list[SearchHit]


# ── describe ──────────────────────────────────────────────────────────────────
class DescribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=200)


class ParameterInfo(BaseModel):
    name: str
    location: str
    required: bool
    description: str
    schema_: dict[str, Any] = Field(alias="schema")
    model_config = ConfigDict(populate_by_name=True)


class DescribeOutput(BaseModel):
    operation_id: str
    api_title: str
    api_version: str
    method: str
    path: str
    summary: str
    description: str
    parameters: list[ParameterInfo]
    request_body_schema: dict[str, Any] | None
    request_body_required: bool
    required_scopes: list[str]
    authentication: str
    responses: dict[str, str]
    requires_idempotency_key: bool
    invocation_skill: str
    side_effect: SideEffect
    deprecated: bool


# ── call ──────────────────────────────────────────────────────────────────────
class CallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=200)
    path_params: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Scalar] = Field(default_factory=dict)
    body: dict[str, Any] | None = None


class CallOutput(BaseModel):
    operation_id: str
    method: str
    path: str
    status_code: int
    ok: bool
    correlation_id: str | None
    upstream_replayed: bool
    duration_ms: float
    response_body: Any
    response_truncated: bool
    retry_after_s: int | None = None
    curl: str


# ── code generation ───────────────────────────────────────────────────────────
class CodegenInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=200)
    path_params: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Scalar] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    languages: list[Literal["curl", "python", "javascript", "java"]] = Field(
        default_factory=lambda: list(codegen.ALL_LANGUAGES), min_length=1
    )


class CodegenOutput(BaseModel):
    operation_id: str
    snippets: dict[str, str]
    notes: list[str]


def _require_op(catalog: ApiCatalog, operation_id: str, ctx: InvocationContext) -> ApiOperation:
    op = catalog.get(operation_id, tenant_id=ctx.principal.tenant_id)
    if op is None:
        raise SkillError(
            SkillErrorCode.NOT_FOUND, f"operation '{operation_id}' is not in your catalog"
        )
    return op


def _validate_request(
    op: ApiOperation, inp: CallInput | CodegenInput, *, placeholders: bool = False
) -> str:
    """Validate against the operation contract and return the expanded path.

    With ``placeholders`` (code generation only), missing path parameters render as
    ``<name>`` and a missing body is allowed; supplied values are still validated.
    """
    declared_query = {p.name for p in op.parameters if p.location == "query"}
    unknown = set(inp.query) - declared_query
    if unknown:
        raise SkillError(
            SkillErrorCode.INVALID_INPUT, f"undeclared query parameters: {sorted(unknown)}"
        )
    path_params = dict(inp.path_params)
    shown: dict[str, str] = {}
    if placeholders:
        for p in op.parameters:
            if p.location == "path" and p.name not in path_params:
                shown[p.name] = f"<{p.name}>"
    template = op.path
    for name, marker in shown.items():
        template = template.replace("{" + name + "}", marker)
    path = expand_path(template, path_params)
    for param in op.parameters:
        if param.location == "query" and param.name in inp.query and param.schema_:
            _check_schema(inp.query[param.name], param.schema_, f"query parameter '{param.name}'")
        if param.location == "path" and param.name in path_params and param.schema_:
            _check_schema(path_params[param.name], param.schema_, f"path parameter '{param.name}'")
    if op.request_body_schema is not None:
        if inp.body is None and op.request_body_required and not placeholders:
            raise SkillError(SkillErrorCode.INVALID_INPUT, "this operation requires a request body")
        if inp.body is not None:
            _check_schema(inp.body, op.request_body_schema, "request body")
    elif inp.body is not None:
        raise SkillError(
            SkillErrorCode.INVALID_INPUT, "this operation does not accept a request body"
        )
    return path


def example_from_schema(schema: dict[str, Any], depth: int = 0) -> Any:
    """Placeholder example for documentation snippets (required fields only)."""
    if depth > 5:
        return None
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        props = schema.get("properties", {})
        return {
            name: example_from_schema(props.get(name, {}), depth + 1)
            for name in schema.get("required", [])
        }
    if kind == "array":
        item = example_from_schema(schema.get("items", {}), depth + 1)
        return [item] * max(1, int(schema.get("minItems", 1)))
    if kind == "integer":
        return int(schema.get("minimum", 1))
    if kind == "number":
        return float(schema.get("minimum", 1))
    if kind == "boolean":
        return True
    return "<string>"


def _check_schema(value: Any, schema: dict[str, Any], what: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
    if errors:
        messages = [
            f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.validator} constraint failed"
            for e in errors[:5]
        ]
        raise SkillError(
            SkillErrorCode.INVALID_INPUT,
            f"{what} does not match the API schema",
            details={"violations": messages},
        )


def build_api_skills(catalog: ApiCatalog, gateway: ApiGateway) -> list[SkillDefinition[Any, Any]]:
    async def search(inp: SearchInput, ctx: InvocationContext) -> SearchOutput:
        hits = catalog.search(
            inp.query, tenant_id=ctx.principal.tenant_id, k=inp.limit, mode=inp.mode
        )
        return SearchOutput(
            results=[
                SearchHit(
                    operation_id=h.operation.operation_id,
                    api=h.operation.api_title,
                    method=h.operation.method,
                    path=h.operation.path,
                    summary=h.operation.summary,
                    scopes=h.operation.scopes,
                    invocation_skill=METHOD_CLASS.get(
                        h.operation.method, ("api.call.read", SideEffect.READ)
                    )[0],
                    score=h.score,
                    rank=h.rank,
                    source_id=h.source_id,
                )
                for h in hits
            ]
        )

    async def describe(inp: DescribeInput, ctx: InvocationContext) -> DescribeOutput:
        op = _require_op(catalog, inp.operation_id, ctx)
        skill_id, side_effect = METHOD_CLASS.get(op.method, ("api.call.read", SideEffect.READ))
        return DescribeOutput(
            operation_id=op.operation_id,
            api_title=op.api_title,
            api_version=op.api_version,
            method=op.method,
            path=op.path,
            summary=op.summary,
            description=op.description,
            parameters=[
                ParameterInfo(
                    name=p.name,
                    location=p.location,
                    required=p.required,
                    description=p.description,
                    schema=p.schema_,
                )
                for p in op.parameters
                if p.name.lower() != "authorization"
            ],
            request_body_schema=op.request_body_schema,
            request_body_required=op.request_body_required,
            required_scopes=op.scopes,
            authentication=(
                "OAuth 2.0 client credentials through the API gateway; "
                f"token must carry: {', '.join(op.scopes) or 'no specific scope'}"
            ),
            responses=op.responses,
            requires_idempotency_key=op.requires_idempotency_key,
            invocation_skill=skill_id,
            side_effect=side_effect,
            deprecated=op.deprecated,
        )

    def checked(
        skill_method_class: str, inp: CallInput, ctx: InvocationContext
    ) -> tuple[ApiOperation, str]:
        op = _require_op(catalog, inp.operation_id, ctx)
        expected_skill, _ = METHOD_CLASS.get(op.method, ("", SideEffect.READ))
        if expected_skill != skill_method_class:
            raise SkillError(
                SkillErrorCode.INVALID_INPUT,
                f"{op.method} {op.path} must be invoked with skill '{expected_skill}'",
            )
        return op, _validate_request(op, inp)

    def make_preflight(skill_method_class: str) -> Any:
        async def preflight(inp: CallInput, ctx: InvocationContext) -> None:
            checked(skill_method_class, inp, ctx)
            gateway.base_url(ctx.environment)  # environment must have a configured gateway

        return preflight

    def make_call(skill_method_class: str) -> Any:
        async def call(inp: CallInput, ctx: InvocationContext) -> CallOutput:
            op, path = checked(skill_method_class, inp, ctx)
            headers: dict[str, str] = {}
            if op.requires_idempotency_key or op.method in {"POST", "PUT", "PATCH", "DELETE"}:
                if ctx.idempotency_key:
                    headers["Idempotency-Key"] = ctx.idempotency_key
            query = {
                k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in inp.query.items()
            }
            response = await gateway.call(
                environment=ctx.environment,
                method=op.method,
                path=path,
                scopes=frozenset(op.scopes),
                query=query,
                body=inp.body,
                headers=headers,
                correlation_id=ctx.correlation_id,
            )
            if response.status_code in RETRYABLE_STATUS:
                raise SkillError(
                    SkillErrorCode.UPSTREAM_UNAVAILABLE,
                    f"upstream returned HTTP {response.status_code}",
                    details={
                        "status_code": response.status_code,
                        "correlation_id": response.correlation_id,
                    },
                )
            body = redact(response.body)
            serialized = json.dumps(body, default=str)
            truncated = len(serialized) > MAX_RESPONSE_PREVIEW
            if truncated:
                body = serialized[:MAX_RESPONSE_PREVIEW]
            retry_after = response.headers.get("retry-after")
            snippet = codegen.render(
                method=op.method,
                base_url=gateway.base_url(ctx.environment),
                path=path,
                query=inp.query,
                body=inp.body,
                headers=headers,
                languages=("curl",),
            )["curl"]
            return CallOutput(
                operation_id=op.operation_id,
                method=op.method,
                path=path,
                status_code=response.status_code,
                ok=200 <= response.status_code < 300,
                correlation_id=response.correlation_id,
                upstream_replayed=response.headers.get("idempotency-replayed") == "true",
                duration_ms=response.elapsed_ms,
                response_body=body,
                response_truncated=truncated,
                retry_after_s=int(retry_after) if retry_after and retry_after.isdigit() else None,
                curl=snippet,
            )

        return call

    async def generate(inp: CodegenInput, ctx: InvocationContext) -> CodegenOutput:
        op = _require_op(catalog, inp.operation_id, ctx)
        path = _validate_request(op, inp, placeholders=True)
        placeholder_body = inp.body is None and op.request_body_schema is not None
        body = example_from_schema(op.request_body_schema or {}) if placeholder_body else inp.body
        headers = {"Idempotency-Key": "<unique-key>"} if op.requires_idempotency_key else {}
        try:
            base_url = gateway.base_url(ctx.environment)
        except SkillError:
            base_url = "https://<gateway-host>"
        snippets = codegen.render(
            method=op.method,
            base_url=base_url,
            path=path,
            query=inp.query,
            body=body,
            headers=headers,
            languages=tuple(inp.languages),
        )
        notes = [
            "Set COPILOT_TOKEN to an OAuth access token with scopes: "
            + (", ".join(op.scopes) or "none"),
            "Snippets are generated text; review before running.",
        ]
        if op.requires_idempotency_key:
            notes.append("Replace <unique-key> with a new idempotency key per logical request.")
        if placeholder_body:
            notes.append(
                "The request body is a schema-derived example with placeholder values; replace "
                "them."
            )
        return CodegenOutput(operation_id=op.operation_id, snippets=snippets, notes=notes)

    call_errors = frozenset(
        {
            SkillErrorCode.NOT_FOUND,
            SkillErrorCode.INVALID_INPUT,
            SkillErrorCode.UPSTREAM_UNAVAILABLE,
            SkillErrorCode.UPSTREAM_ERROR,
            SkillErrorCode.TIMEOUT,
            SkillErrorCode.DESTINATION_BLOCKED,
            SkillErrorCode.RESPONSE_TOO_LARGE,
            SkillErrorCode.NOT_CONFIGURED,
        }
    )
    retry = RetryPolicy(max_attempts=3, initial_backoff_s=0.2, max_backoff_s=1.0)
    return [
        SkillDefinition(
            id="api.search",
            name="Search API catalog",
            version="1.0.0",
            description="Find API operations matching a natural-language query. Read-only.",
            input_model=SearchInput,
            output_model=SearchOutput,
            handler=search,
            required_permissions=frozenset({CATALOG_READ}),
            side_effect=SideEffect.READ,
            timeout_s=5,
            audit_required=False,
        ),
        SkillDefinition(
            id="api.describe",
            name="Describe API operation",
            version="1.0.0",
            description="Explain an operation's authentication, scopes, parameters, request "
            "schema and responses.",
            input_model=DescribeInput,
            output_model=DescribeOutput,
            handler=describe,
            required_permissions=frozenset({CATALOG_READ}),
            side_effect=SideEffect.READ,
            timeout_s=5,
            audit_required=False,
            error_codes=frozenset({SkillErrorCode.NOT_FOUND}),
        ),
        SkillDefinition(
            id="api.call.read",
            name="Call API (read)",
            version="1.0.0",
            description="Invoke a GET/HEAD operation through the configured gateway.",
            input_model=CallInput,
            output_model=CallOutput,
            handler=make_call("api.call.read"),
            preflight=make_preflight("api.call.read"),
            required_permissions=frozenset({API_INVOKE_READ}),
            side_effect=SideEffect.READ,
            timeout_s=20,
            retry=retry,
            error_codes=call_errors,
        ),
        SkillDefinition(
            id="api.call.write",
            name="Call API (write)",
            version="1.0.0",
            description="Invoke a POST/PUT/PATCH operation. Requires an approval bound to the "
            "exact call.",
            input_model=CallInput,
            output_model=CallOutput,
            handler=make_call("api.call.write"),
            preflight=make_preflight("api.call.write"),
            required_permissions=frozenset({API_INVOKE_WRITE}),
            side_effect=SideEffect.WRITE,
            timeout_s=20,
            retry=retry,
            idempotency_required=True,
            error_codes=call_errors,
        ),
        SkillDefinition(
            id="api.call.delete",
            name="Call API (delete)",
            version="1.0.0",
            description="Invoke a DELETE operation. Requires an approval from someone other than "
            "the requester.",
            input_model=CallInput,
            output_model=CallOutput,
            handler=make_call("api.call.delete"),
            preflight=make_preflight("api.call.delete"),
            required_permissions=frozenset({API_INVOKE_DELETE}),
            side_effect=SideEffect.DESTRUCTIVE,
            timeout_s=20,
            retry=retry,
            idempotency_required=True,
            error_codes=call_errors,
        ),
        SkillDefinition(
            id="code.generate",
            name="Generate request code",
            version="1.0.0",
            description="Generate cURL, Python, JavaScript and Java snippets for an operation. "
            "Never includes credentials.",
            input_model=CodegenInput,
            output_model=CodegenOutput,
            handler=generate,
            required_permissions=frozenset({CODE_GENERATE}),
            side_effect=SideEffect.NONE,
            timeout_s=5,
            audit_required=False,
            error_codes=frozenset({SkillErrorCode.NOT_FOUND, SkillErrorCode.INVALID_INPUT}),
        ),
    ]
