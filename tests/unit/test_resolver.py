"""G10: skills declare their intents; the resolver is built from the registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from ai.agent.contracts import Intent
from ai.agent.resolver import IntentResolver, ResolverConfigError
from skills.runtime.contracts import SideEffect, SkillDefinition
from skills.runtime.registry import SkillRegistry
from tests.support import build_harness

# The hand-maintained table this replaced (as of ADR-0011), frozen here as the oracle.
LEGACY = {
    Intent.API_DISCOVERY: {"api.search", "api.describe"},
    Intent.API_EXPLANATION: {"api.search", "api.describe"},
    Intent.CODE_GENERATION: {"api.search", "api.describe", "code.generate"},
    Intent.API_EXECUTION: {
        "api.search",
        "api.describe",
        "api.call.read",
        "api.call.write",
        "api.call.delete",
        "docs.search",
    },
    Intent.TROUBLESHOOTING: {"docs.search", "token.inspect", "api.search", "api.describe"},
    Intent.TOKEN_INSPECTION: {"token.inspect", "docs.search"},
    Intent.DOCS_QUESTION: {"docs.search", "api.search"},
    Intent.CLARIFICATION_NEEDED: set(),
    Intent.UNSUPPORTED: set(),
}


class _Nothing(BaseModel):
    pass


async def _noop(_: _Nothing, __: object) -> _Nothing:
    return _Nothing()


def _skill(skill_id: str, intents: set[str]) -> SkillDefinition[_Nothing, _Nothing]:
    return SkillDefinition(
        id=skill_id,
        name=skill_id,
        version="1",
        description="test",
        input_model=_Nothing,
        output_model=_Nothing,
        handler=_noop,  # type: ignore[arg-type]
        required_permissions=frozenset({"x"}),
        side_effect=SideEffect.NONE,
        intents=frozenset(intents),
    )


def test_registry_built_resolver_equals_the_legacy_table() -> None:
    resolver = IntentResolver(build_harness().services.registry)
    for intent in Intent:
        assert set(resolver.resolve(intent).ids) == LEGACY[intent], intent
    # Order is explicit (SkillDefinition.order), not registration order.
    assert resolver.resolve(Intent.API_EXECUTION).ids == [
        "api.search",
        "api.describe",
        "api.call.read",
        "api.call.write",
        "api.call.delete",
        "docs.search",
    ]
    resolver.validate()


def test_a_new_skill_with_an_intent_is_available_without_editing_the_resolver() -> None:
    registry = build_harness().services.registry
    registry.register(_skill("notes.lookup", {"docs_question"}))
    resolver = IntentResolver(registry)
    assert "notes.lookup" in resolver.resolve(Intent.DOCS_QUESTION).ids
    assert "notes.lookup" not in resolver.resolve(Intent.API_EXECUTION).ids


def test_startup_fails_on_an_unknown_intent() -> None:
    registry = build_harness().services.registry
    registry.register(_skill("bad.skill", {"api_discovery", "api_discovry"}))
    with pytest.raises(ResolverConfigError, match=r"bad.skill.*api_discovry"):
        IntentResolver(registry).validate()


def test_startup_fails_when_an_actionable_intent_has_no_skills() -> None:
    registry = SkillRegistry()
    registry.register(_skill("only.one", {"api_discovery"}))
    with pytest.raises(ResolverConfigError, match=r"resolves to no skills"):
        IntentResolver(registry).validate()
