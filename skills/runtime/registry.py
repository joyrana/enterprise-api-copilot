"""In-process skill registry. Discovery only — no execution happens here."""

from __future__ import annotations

from typing import Any

from skills.runtime.contracts import SkillDefinition, SkillDescriptor


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition[Any, Any]] = {}

    def register(self, skill: SkillDefinition[Any, Any]) -> None:
        if skill.id in self._skills:
            raise ValueError(f"skill '{skill.id}' is already registered")
        self._skills[skill.id] = skill

    def get(self, skill_id: str) -> SkillDefinition[Any, Any] | None:
        return self._skills.get(skill_id)

    def ids(self) -> list[str]:
        return sorted(self._skills)

    def descriptors(self) -> list[SkillDescriptor]:
        return [self._skills[i].descriptor() for i in self.ids()]

    def __contains__(self, skill_id: object) -> bool:
        return skill_id in self._skills

    def __len__(self) -> int:
        return len(self._skills)
