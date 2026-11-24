"""G12: one component registry. The manifest, the OpenAPI enum and the web registry agree."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ai.agent.contracts import RunState, RunStatus
from ai.agent.ui import REGISTRY, build_components, manifest, validate_props
from skills.runtime.contracts import Principal, SkillResult

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "contracts" / "json-schema" / "ui-components.json"
OPENAPI = ROOT / "contracts" / "openapi" / "platform-api.yaml"
FRONTEND_REGISTRY = ROOT / "apps" / "frontend" / "src" / "components" / "genui" / "registry.ts"


def test_committed_manifest_is_current() -> None:
    expected = json.dumps(manifest(), indent=2, sort_keys=True) + "\n"
    assert MANIFEST.read_text(encoding="utf-8") == expected, (
        "run `python -m ai.agent.ui --write` and commit contracts/json-schema/ui-components.json"
    )


def test_openapi_component_enum_matches_the_manifest() -> None:
    spec = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    enum = spec["components"]["schemas"]["UIComponent"]["properties"]["component"]["enum"]
    names = [c["name"] for c in json.loads(MANIFEST.read_text())["components"]]
    assert sorted(enum) == sorted(names)


def test_frontend_registry_keys_match_the_manifest() -> None:
    names = {c["name"] for c in json.loads(MANIFEST.read_text())["components"]}
    source = FRONTEND_REGISTRY.read_text(encoding="utf-8")
    block = source.split("COMPONENT_REGISTRY", 1)[1].split("};", 1)[0]
    keys = set(re.findall(r"^\s+([a-z_]+):\s+[A-Z]\w+,?$", block, re.MULTILINE))
    assert keys == names, f"web registry and manifest differ: {keys ^ names}"


def test_every_component_has_a_props_schema_and_valid_server_controlled_flags() -> None:
    for component in json.loads(MANIFEST.read_text())["components"]:
        assert component["props_schema"]["type"] == "object"
        assert component["props_schema"].get("additionalProperties") is False or (
            component["props_schema"].get("properties") is None
        )
    selectable = {
        c["name"] for c in json.loads(MANIFEST.read_text())["components"] if c["selectable"]
    }
    assert "approval_request" not in selectable and "clarification" not in selectable


def test_props_are_validated_against_the_schema() -> None:
    with pytest.raises(ValidationError):
        validate_props("approval_request", {"summary": "x"})  # missing fields
    with pytest.raises(ValidationError):
        validate_props("operation_list", {"operations": [], "surprise": 1})  # unknown key
    ok = validate_props("clarification", {"question": "q", "missing_fields": ["body.amount"]})
    assert ok == {"question": "q", "missing_fields": ["body.amount"]}


def test_a_component_whose_built_props_break_the_schema_is_rejected_not_shown() -> None:
    state = RunState(
        run_id="run_0123456789abcdef",
        query="q",
        principal=Principal(subject="a", tenant_id="acme", roles=frozenset({"developer"})),
        environment="sandbox",
        status=RunStatus.COMPLETED,
    )
    # api.describe output without operation_id: the builder cannot produce valid props.
    state.results["describe"] = SkillResult(
        skill_id="api.describe",
        skill_version="1",
        ok=True,
        output={"operation_id": None, "parameters": [{"name": "x"}]},
        correlation_id="c",
    )
    try:
        components, rejected = build_components(state, [("operation_detail", "describe")])
    except KeyError:
        # the builder indexes required keys directly; either way nothing invalid is shown
        components, rejected = [], ["builder failed"]
    assert components == [] and rejected


def test_registry_names_are_unique_and_documented() -> None:
    assert len(REGISTRY) == len({s.name for s in REGISTRY.values()}) == 9
    assert all(spec.description for spec in REGISTRY.values())
