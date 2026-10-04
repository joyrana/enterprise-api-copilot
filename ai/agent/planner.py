"""Template planner: intent → bounded, typed plan.

Known operations use fixed templates (principle 4). Steps may reference earlier outputs
with ``{"$from": step, "path": "a.0.b"}``; the API-call step uses ``skill_id="@bind"``
and is resolved from ``api.describe`` output to exactly one of the three call skills.
"""

from __future__ import annotations

from typing import Any, Protocol

from ai.agent.contracts import Intent, IntentResult, Plan, PlanStep
from ai.agent.intent import operation_query

BIND_SKILL = "@bind"
CALL_SKILLS = frozenset({"api.call.read", "api.call.write", "api.call.delete"})


def ref(step: str, path: str) -> dict[str, str]:
    return {"$from": step, "path": path}


class Planner(Protocol):
    name: str

    def plan(self, query: str, intent: IntentResult) -> Plan: ...


class TemplatePlanner:
    name = "template-v1"

    def plan(self, query: str, intent: IntentResult) -> Plan:
        ent = intent.entities
        steps: list[PlanStep] = []
        top_op = ref("search", "results.0.operation_id")
        op_query = operation_query(query) or query
        match intent.intent:
            case Intent.API_DISCOVERY:
                steps = [
                    PlanStep(
                        step_id="search",
                        skill_id="api.search",
                        arguments={"query": query, "limit": 5},
                        purpose="find matching operations",
                    )
                ]
            case Intent.API_EXPLANATION:
                steps = [
                    PlanStep(
                        step_id="search",
                        skill_id="api.search",
                        arguments={"query": op_query, "limit": 3},
                        purpose="find the operation",
                    ),
                    PlanStep(
                        step_id="describe",
                        skill_id="api.describe",
                        arguments={"operation_id": top_op},
                        purpose="explain auth, scopes and schema",
                    ),
                ]
            case Intent.CODE_GENERATION:
                args: dict[str, Any] = {"operation_id": top_op}
                if ent.languages:
                    args["languages"] = ent.languages
                steps = [
                    PlanStep(
                        step_id="search",
                        skill_id="api.search",
                        arguments={"query": op_query, "limit": 3},
                        purpose="find the operation",
                    ),
                    PlanStep(
                        step_id="codegen",
                        skill_id="code.generate",
                        arguments=args,
                        purpose="generate request examples",
                    ),
                ]
            case Intent.API_EXECUTION:
                steps = [
                    PlanStep(
                        step_id="search",
                        skill_id="api.search",
                        arguments={"query": op_query, "limit": 3},
                        purpose="find the operation",
                    ),
                    PlanStep(
                        step_id="describe",
                        skill_id="api.describe",
                        arguments={"operation_id": top_op},
                        purpose="load the contract",
                    ),
                    PlanStep(
                        step_id="call",
                        skill_id=BIND_SKILL,
                        arguments={},
                        purpose="execute with arguments bound from the request",
                    ),
                ]
            case Intent.TOKEN_INSPECTION:
                steps = [
                    PlanStep(
                        step_id="inspect",
                        skill_id="token.inspect",
                        arguments={"token": ent.jwt or ""},
                        purpose="decode and explain the token",
                    )
                ]
            case Intent.TROUBLESHOOTING:
                steps = [
                    PlanStep(
                        step_id="docs",
                        skill_id="docs.search",
                        arguments={"query": query, "k": 5},
                        purpose="find documented causes",
                    )
                ]
                if ent.jwt:
                    steps.append(
                        PlanStep(
                            step_id="inspect",
                            skill_id="token.inspect",
                            arguments={"token": ent.jwt},
                            purpose="check the token",
                        )
                    )
            case Intent.DOCS_QUESTION:
                steps = [
                    PlanStep(
                        step_id="docs",
                        skill_id="docs.search",
                        arguments={"query": query, "k": 5},
                        purpose="answer from documentation",
                    )
                ]
            case _:
                steps = []
        return Plan(intent=intent.intent, steps=steps, planner=self.name)
