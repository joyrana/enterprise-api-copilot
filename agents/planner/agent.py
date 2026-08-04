"""
Enterprise API Copilot — Planner Agent

The Planner takes the classified intent and user query, then generates
a structured execution plan consisting of ordered MCP skill invocations.

TODO(#110): Implement plan generation using LLM structured output.
TODO(#111): Add plan validation and sanitization.
TODO(#112): Support parallel step execution where order doesn't matter.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.shared.state import AgentState, ExecutionStatus, ExecutionStep

logger = logging.getLogger(__name__)


async def planner_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Planner agent node.

    Generates a structured execution plan from the user query and intent.
    Each step in the plan maps to a specific MCP skill invocation.

    Args:
        state: Current agent state with intent classified.
        config: LangGraph runnable config.

    Returns:
        Updated state dict with plan field populated.
    """
    logger.info(
        "Planner generating execution plan",
        extra={
            "session_id": state.session_id,
            "intent": state.intent,
        },
    )

    # TODO(#110): Implement real plan generation with LLM
    # Example:
    #
    # llm = ChatOpenAI(model="gpt-4o", temperature=0)
    # structured_llm = llm.with_structured_output(ExecutionPlan)
    # plan = await structured_llm.ainvoke([
    #     SystemMessage(content=PLANNER_SYSTEM_PROMPT),
    #     HumanMessage(content=f"Intent: {state.intent}\nQuery: {state.user_query}"),
    # ])

    # Placeholder plan for scaffolding purposes
    placeholder_plan = [
        ExecutionStep(
            step_id=str(uuid.uuid4()),
            skill="api-discovery",
            description="Discover the API matching the user request",
            parameters={"query": state.user_query},
        ),
        ExecutionStep(
            step_id=str(uuid.uuid4()),
            skill="jwt",
            description="Obtain authentication token from Apigee",
            parameters={},
        ),
        ExecutionStep(
            step_id=str(uuid.uuid4()),
            skill="api-executor",
            description="Execute the discovered API with the obtained token",
            parameters={},
        ),
        ExecutionStep(
            step_id=str(uuid.uuid4()),
            skill="sdk-generator",
            description="Generate curl and SDK equivalents",
            parameters={},
        ),
    ]

    logger.info("Plan generated with %d steps", len(placeholder_plan))

    return {
        "plan": placeholder_plan,
        "current_step_index": 0,
        "status": ExecutionStatus.EXECUTING,
    }
