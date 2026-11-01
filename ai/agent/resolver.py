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

INTENT_SKILLS: dict[Intent, tuple[str, ...]] = {
    Intent.API_DISCOVERY: ("api.search", "api.describe"),
    Intent.API_EXPLANATION: ("api.search", "api.describe"),
    Intent.CODE_GENERATION: ("api.search", "api.describe", "code.generate"),
    Intent.API_EXECUTION: (
        "api.search",
        "api.describe",
        "api.call.read",
        "api.call.write",
        "api.call.delete",
        "docs.search",
    ),
    Intent.TROUBLESHOOTING: ("docs.search", "token.inspect", "api.search", "api.describe"),
    Intent.TOKEN_INSPECTION: ("token.inspect", "docs.search"),
    Intent.DOCS_QUESTION: ("docs.search", "api.search"),
    Intent.CLARIFICATION_NEEDED: (),
    Intent.UNSUPPORTED: (),
}


class ResolvedSkills(BaseModel):
    intent: Intent
    skills: list[SkillDescriptor]

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.skills]


class IntentResolver:
    name = "intent-table-v1"

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def resolve(self, intent: Intent) -> ResolvedSkills:
        skills = []
        for skill_id in INTENT_SKILLS.get(intent, ()):
            definition = self.registry.get(skill_id)
            if definition is not None:
                skills.append(definition.descriptor())
        return ResolvedSkills(intent=intent, skills=skills)
