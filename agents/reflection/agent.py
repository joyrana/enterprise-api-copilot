"""
Enterprise API Copilot — Reflection Agent

The Reflection agent analyzes failures and determines whether to:
- Retry the current step with modifications
- Replan from scratch
- Fail gracefully with a helpful error message

TODO(#120): Implement root cause analysis using LLM.
TODO(#121): Add structured retry strategies per error type.
TODO(#122): Track reflection history to avoid infinite loops.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from agents.shared.state import AgentState, ExecutionStatus

logger = logging.getLogger(__name__)


async def reflection_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Reflection agent node.

    Analyzes the current error and decides the recovery strategy.

    Args:
        state: Current agent state with error information.
        config: LangGraph runnable config.

    Returns:
        Updated state dict with reflection notes and retry decision.
    """
    logger.warning(
        "Reflection triggered",
        extra={
            "session_id": state.session_id,
            "error": state.error,
            "retry_count": state.retry_count,
        },
    )

    if state.retry_count >= state.max_retries:
        logger.error("Max retries exceeded. Failing gracefully.")
        return {
            "status": ExecutionStatus.FAILED,
            "reflection_notes": state.reflection_notes
            + [f"Max retries ({state.max_retries}) exceeded. Last error: {state.error}"],
        }

    # TODO(#120): Implement real reflection logic
    reflection_note = f"Retry attempt {state.retry_count + 1}: {state.error}"
    logger.info("Reflection note: %s", reflection_note)

    return {
        "retry_count": state.retry_count + 1,
        "error": None,
        "reflection_notes": state.reflection_notes + [reflection_note],
    }


def route_after_reflection(
    state: AgentState,
) -> Literal["planner", "executor", "end"]:
    """
    Routing after reflection based on retry decision.
    """
    if state.status == ExecutionStatus.FAILED:
        return "end"

    # TODO(#121): Decide between replanning and retry based on error type
    return "executor"
