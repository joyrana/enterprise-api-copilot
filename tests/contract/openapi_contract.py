"""Minimal OpenAPI 3.1 response-contract checker used by the contract tests.

* resolves ``#/components/...`` and ``./platform-api.yaml#/...`` references;
* fails on undocumented status codes and on bodies that violate the response schema;
* records which (method, path template) operations were exercised, so a test can assert
  that every documented operation is covered.

Implementation-independent: point it at the Spring Boot backend later with the same tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import yaml

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "openapi"


def _rewrite_refs(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: (
                v.replace("./platform-api.yaml#", "#")
                if k == "$ref" and isinstance(v, str)
                else _rewrite_refs(v)
            )
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


class Contract:
    def __init__(self, filename: str) -> None:
        spec = yaml.safe_load((CONTRACTS / filename).read_text(encoding="utf-8"))
        platform = yaml.safe_load((CONTRACTS / "platform-api.yaml").read_text(encoding="utf-8"))
        components = {**platform["components"], **spec.get("components", {})}
        for key in ("schemas", "responses"):
            components[key] = {
                **platform["components"].get(key, {}),
                **spec.get("components", {}).get(key, {}),
            }
        self.spec = _rewrite_refs(spec)
        self.components = _rewrite_refs(components)
        self.covered: set[tuple[str, str]] = set()
        self._templates = [
            (re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", path) + "$"), path)
            for path in self.spec["paths"]
        ]

    def operations(self) -> set[tuple[str, str]]:
        return {
            (method.upper(), path)
            for path, item in self.spec["paths"].items()
            for method in item
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def _template(self, path: str) -> str:
        matches = [tpl for rx, tpl in self._templates if rx.match(path)]
        if not matches:
            raise AssertionError(f"undocumented path {path}")
        return min(matches, key=lambda t: t.count("{"))  # prefer literal segments

    def check(self, response: httpx.Response) -> httpx.Response:
        request = response.request
        template = self._template(request.url.path)
        method = request.method.lower()
        operation = self.spec["paths"][template].get(method)
        if operation is None:
            raise AssertionError(f"undocumented method {method.upper()} {template}")
        self.covered.add((method.upper(), template))
        documented = operation["responses"]
        spec_response = documented.get(str(response.status_code))
        if spec_response is None:
            raise AssertionError(
                f"{method.upper()} {template} returned undocumented {response.status_code}: {response.text[:200]}"
            )
        if "$ref" in spec_response:
            spec_response = self.components["responses"][spec_response["$ref"].rsplit("/", 1)[-1]]
        schema = spec_response.get("content", {}).get("application/json", {}).get("schema")
        if schema is not None:
            validator = jsonschema.Draft202012Validator({**schema, "components": self.components})
            errors = list(validator.iter_errors(response.json()))
            if errors:
                raise AssertionError(
                    f"{method.upper()} {template} {response.status_code} violates contract: {errors[0].message}"
                )
        return response
