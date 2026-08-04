"""
Enterprise API Copilot — Supervisor Agent

The Supervisor is the entry point of the agent graph. It:
1. Classifies the user's intent
2. Decides whether the request is supported
3. Routes to the appropriate downstream agent

TODO(#100): Implement intent classification using structured output.
TODO(#101): Add support for multi-intent queries.
TODO(#102): Add conversation context injection from memory.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from ai.shared.state import AgentState, ExecutionStatus

logger = logging.getLogger(__name__)

# Intent categories the supervisor can classify
SUPPORTED_INTENTS = [
    "api_discovery",       # "What APIs are available for payments?"
    "api_execution",       # "Create a payment of ₹500"
    "api_explanation",     # "How does the authentication flow work?"
    "api_troubleshooting", # "Why is my API call returning 401?"
    "general_question",    # "What is the rate limit for the Orders API?"
]

UNSUPPORTED_INTENTS = [
    "off_topic",          # Unrelated to APIs
    "harmful",            # Potentially harmful requests
]


async def supervisor_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Supervisor agent node.

    Classifies the user intent and determines the routing decision.

    Args:
        state: Current agent state.
        config: LangGraph runnable config.

    Returns:
        Updated state dict with intent and status fields.
    """
    logger.info(
        "Supervisor processing query",
        extra={
            "session_id": state.session_id,
            "query_length": len(state.user_query),
        },
    )

    # TODO(#100): Implement real intent classification with LLM structured output
    intent = "api_execution"  # TODO(#100): Replace with real classification

    logger.info("Intent classified: %s", intent)

    return {
        "intent": intent,
        "status": ExecutionStatus.PLANNING,
    }


def route_after_supervisor(
    state: AgentState,
) -> Literal["planner", "end"]:
    """
    Routing function called after the supervisor node.

    Returns:
        Next node name or "end" if the request cannot be handled.
    """
    if state.intent in UNSUPPORTED_INTENTS:
        logger.warning("Unsupported intent: %s", state.intent)
        return "end"
    return "planner"
