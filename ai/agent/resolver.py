"""Intent resolver: intent → the skills the agent may use for it.

This is the capability boundary for the LLM planner. The planner only ever sees, and can
only ever invoke, the skills resolved here, so a documentation question can never reach a
write skill however the model (or an injected document) is steered. Skills missing from
the registry are skipped; the runtime still enforces permissions, environments and
approvals on every call.
"""

from __future__ import annotations

from pydantic import BaseModel

from ai.agent.contracts import Intent
from skills.runtime.contracts import SkillDescriptor
from skills.runtime.registry import SkillRegistry

# Intents with no skills by design: nothing runs for them.
INERT_INTENTS = frozenset({Intent.CLARIFICATION_NEEDED, Intent.UNSUPPORTED})


class ResolverConfigError(RuntimeError):
    """The skill registry and the intent set disagree (caught at start-up)."""


class ResolvedSkills(BaseModel):
    intent: Intent
    skills: list[SkillDescriptor]

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.skills]


class IntentResolver:
    """Built from the skills' own ``intents`` declarations; no table to keep in sync."""

    name = "intent-registry-v1"

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def resolve(self, intent: Intent) -> ResolvedSkills:
        chosen = sorted(
            (d for d in self.registry.definitions() if intent.value in d.intents),
            key=lambda d: (d.order, d.id),
        )
        return ResolvedSkills(intent=intent, skills=[d.descriptor() for d in chosen])

    def validate(self) -> None:
        """Fail fast on a registry that cannot serve the agent.

        * a skill declares an intent that does not exist (typo, stale name);
        * an actionable intent resolves to no skill at all.
        """
        known = {i.value for i in Intent}
        for definition in self.registry.definitions():
            unknown = sorted(definition.intents - known)
            if unknown:
                raise ResolverConfigError(
                    f"skill '{definition.id}' declares unknown intent(s): {', '.join(unknown)}"
                )
        for intent in Intent:
            if intent not in INERT_INTENTS and not self.resolve(intent).skills:
                raise ResolverConfigError(
                    f"intent '{intent.value}' resolves to no skills; register one that "
                    "declares it in its `intents`"
                )
