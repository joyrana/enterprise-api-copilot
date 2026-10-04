"""OpenAPI 3.x ingestion into a typed operation catalog.

Untrusted-input rules (threat model T2):

* size limit before parsing; ``yaml.safe_load`` only;
* only local ``#/...`` references are resolved, with a depth bound; external references
  are not fetched;
* the spec's ``servers`` block is recorded for information but **never used** to build
  execution URLs — the gateway base URL comes from configuration only.
"""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, Field

from ai.knowledge.documents import Document, SourceType

MAX_SPEC_BYTES = 2_000_000
MAX_REF_DEPTH = 8
MAX_OPERATIONS = 2000
HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")


class SpecError(ValueError):
    pass


class ApiParameter(BaseModel):
    name: str
    location: str  # path | query | header | cookie
    required: bool = False
    description: str = ""
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = {"populate_by_name": True}


class ApiOperation(BaseModel):
    api_id: str
    api_version: str
    api_title: str
    operation_id: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    parameters: list[ApiParameter] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    request_body_required: bool = False
    responses: dict[str, str] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)
    security_schemes: list[str] = Field(default_factory=list)
    deprecated: bool = False

    @property
    def requires_idempotency_key(self) -> bool:
        return any(
            p.location == "header" and p.name.lower() == "idempotency-key" and p.required
            for p in self.parameters
        )

    def index_text(self) -> str:
        params = " ".join(f"{p.name} {p.description}" for p in self.parameters)
        responses = " ".join(f"{code} {desc}" for code, desc in self.responses.items())
        body_fields = ""
        if self.request_body_schema:
            body_fields = " ".join(self.request_body_schema.get("properties", {}).keys())
        return " ".join(
            [
                self.operation_id,
                self.method.upper(),
                self.path,
                self.summary,
                self.description,
                " ".join(self.tags),
                self.api_title,
                params,
                body_fields,
                " ".join(self.scopes),
                responses,
            ]
        )


class ApiSpec(BaseModel):
    api_id: str
    title: str
    version: str
    operations: list[ApiOperation]
    declared_servers: list[str] = Field(default_factory=list)  # informational only
    token_urls: list[str] = Field(default_factory=list)  # informational only


MAX_NESTING = 64


def _resolve(node: Any, root: dict[str, Any], hops: int = 0, nesting: int = 0) -> Any:
    """Inline local ``$ref``s. ``hops`` bounds reference chains (and cycles); ``nesting``
    bounds structural depth so hostile documents cannot exhaust the stack."""
    if nesting > MAX_NESTING:
        raise SpecError("spec nesting too deep")
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith("#/"):
                return {"x-unresolved": "external reference not fetched"}
            if hops >= MAX_REF_DEPTH:
                return {"x-unresolved": "max reference depth exceeded"}
            target: Any = root
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part not in target:
                    raise SpecError(f"unresolvable reference {ref}")
                target = target[part]
            return _resolve(target, root, hops + 1, nesting + 1)
        return {k: _resolve(v, root, hops, nesting + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root, hops, nesting + 1) for v in node]
    return node


def load_spec(raw: str | bytes | dict[str, Any], *, api_id: str) -> ApiSpec:
    if isinstance(raw, str | bytes):
        if len(raw) > MAX_SPEC_BYTES:
            raise SpecError("spec exceeds size limit")
        data = yaml.safe_load(raw)
    else:
        data = raw
    if not isinstance(data, dict) or not str(data.get("openapi", "")).startswith("3."):
        raise SpecError("only OpenAPI 3.x documents are supported")
    info = data.get("info") or {}
    title = str(info.get("title", api_id))
    version = str(info.get("version", "0"))
    schemes = (data.get("components") or {}).get("securitySchemes") or {}
    global_security = data.get("security") or []
    token_urls: list[str] = []
    for scheme in schemes.values():
        for flow in ((scheme or {}).get("flows") or {}).values():
            if isinstance(flow, dict) and "tokenUrl" in flow:
                token_urls.append(str(flow["tokenUrl"]))

    operations: list[ApiOperation] = []
    for path, item in (data.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared_params = item.get("parameters") or []
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            if len(operations) >= MAX_OPERATIONS:
                raise SpecError("too many operations")
            op = _resolve(op, data)
            params_raw = _resolve(shared_params, data) + (op.get("parameters") or [])
            params = [
                ApiParameter(
                    name=str(p.get("name", "")),
                    location=str(p.get("in", "")),
                    required=bool(p.get("required", p.get("in") == "path")),
                    description=str(p.get("description", "")),
                    schema=p.get("schema") or {},
                )
                for p in params_raw
                if isinstance(p, dict)
            ]
            body = op.get("requestBody") or {}
            body_schema = None
            content = body.get("content") or {}
            if "application/json" in content:
                body_schema = (content["application/json"] or {}).get("schema")
            security = op.get("security", global_security) or []
            scopes: list[str] = []
            scheme_names: list[str] = []
            for requirement in security:
                for name, req_scopes in (requirement or {}).items():
                    scheme_names.append(str(name))
                    scopes.extend(str(s) for s in req_scopes or [])
            operations.append(
                ApiOperation(
                    api_id=api_id,
                    api_version=version,
                    api_title=title,
                    operation_id=str(op.get("operationId") or f"{method}_{path}"),
                    method=method.upper(),
                    path=str(path),
                    summary=str(op.get("summary", "")),
                    description=str(op.get("description", "")),
                    tags=[str(t) for t in op.get("tags") or []],
                    parameters=params,
                    request_body_schema=body_schema,
                    request_body_required=bool(body.get("required", False)),
                    responses={
                        str(code): str((resp or {}).get("description", ""))
                        for code, resp in (op.get("responses") or {}).items()
                    },
                    scopes=sorted(set(scopes)),
                    security_schemes=sorted(set(scheme_names)),
                    deprecated=bool(op.get("deprecated", False)),
                )
            )
    return ApiSpec(
        api_id=api_id,
        title=title,
        version=version,
        operations=operations,
        declared_servers=[
            str(s.get("url", "")) for s in data.get("servers") or [] if isinstance(s, dict)
        ],
        token_urls=token_urls,
    )


def operation_documents(spec: ApiSpec, *, tenant_id: str) -> list[Document]:
    """One knowledge document per operation, so retrieval can cite an operation directly."""
    return [
        Document(
            doc_id=f"{spec.api_id}:{op.operation_id}",
            version=spec.version,
            tenant_id=tenant_id,
            source_type=SourceType.OPENAPI_OPERATION,
            title=f"{op.method} {op.path}",
            uri=f"openapi://{spec.api_id}/{op.operation_id}",
            text=op.index_text(),
            metadata={"api_id": spec.api_id, "operation_id": op.operation_id},
        )
        for op in spec.operations
    ]
