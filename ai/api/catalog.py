"""Catalog reads (skills, API search, API description), shared by the platform facade and
the internal agent API (the Spring platform proxies to the latter).

Reads go through the skill runtime, so the caller's permissions apply exactly as they do for
the agent. Skill errors map to the platform ``ApiError`` statuses.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from ai.api.http import ApiProblemError
from ai.bootstrap import Services
from skills.runtime.contracts import InvocationContext, Principal
from skills.runtime.errors import SkillErrorCode

SKILL_STATUS = {
    SkillErrorCode.FORBIDDEN: (403, "ACCESS_DENIED"),
    SkillErrorCode.NOT_FOUND: (404, "RESOURCE_NOT_FOUND"),
    SkillErrorCode.INVALID_INPUT: (400, "VALIDATION_ERROR"),
    SkillErrorCode.ENVIRONMENT_NOT_ALLOWED: (403, "ACCESS_DENIED"),
}


class CatalogApi:
    def __init__(self, services: Services, environment: str) -> None:
        self._services = services
        self._environment = environment

    def skills(self) -> dict[str, Any]:
        return {
            "skills": [
                {
                    "id": d.id,
                    "name": d.name,
                    "version": d.version,
                    "description": d.description,
                    "side_effect": d.side_effect.value,
                    "required_permissions": d.required_permissions,
                    "requires_approval": d.requires_approval,
                }
                for d in self._services.registry.descriptors()
            ]
        }

    async def _skill(
        self, skill_id: str, args: dict[str, object], principal: Principal
    ) -> dict[str, Any]:
        ctx = InvocationContext(
            principal=principal,
            environment=self._environment,
            correlation_id=f"api_{uuid.uuid4().hex[:16]}",
        )
        result = await self._services.runtime.invoke(skill_id, args, ctx)
        if result.ok and result.output is not None:
            return result.output
        code = result.error.code if result.error else SkillErrorCode.INTERNAL_ERROR
        status, api_code = SKILL_STATUS.get(
            code, (502 if code.value.startswith("UPSTREAM") else 500, code.value)
        )
        raise ApiProblemError(
            status, api_code, result.error.message if result.error else "skill failed"
        )

    async def search(self, params: Mapping[str, str], principal: Principal) -> dict[str, Any]:
        query = params.get("q", "")
        try:
            limit = int(params.get("limit", "5"))
        except ValueError as exc:
            raise ApiProblemError(400, "VALIDATION_ERROR", "limit must be an integer") from exc
        if not query or len(query) > 500 or not 1 <= limit <= 20:
            raise ApiProblemError(
                400, "VALIDATION_ERROR", "q is required (max 500 chars) and limit must be 1-20"
            )
        return await self._skill("api.search", {"query": query, "limit": limit}, principal)

    async def describe(self, operation_id: str, principal: Principal) -> dict[str, Any]:
        return await self._skill("api.describe", {"operation_id": operation_id}, principal)
