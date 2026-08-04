"""
Enterprise API Copilot — Memory Agent

Manages conversation memory: reads relevant context before each run
and writes important facts after successful execution.

TODO(#130): Implement vector store integration for semantic memory retrieval.
TODO(#131): Implement memory summarization for long conversations.
TODO(#132): Add user preference learning.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from ai.shared.state import AgentState, ExecutionStatus

logger = logging.getLogger(__name__)


async def memory_read_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Memory read node — retrieves relevant context before planning."""
    logger.debug("Memory read: retrieving context for session %s", state.session_id)
    return {}


async def memory_write_node(
    state: AgentState,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Memory write node — persists important facts after execution."""
    if state.status != ExecutionStatus.COMPLETED:
        return {}

    logger.debug("Memory write: persisting context for session %s", state.session_id)
    return {}
