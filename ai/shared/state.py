"""
Enterprise API Copilot — Shared Agent State

Defines the LangGraph state schema shared across all agents.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Execution lifecycle status."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    REFLECTING = "REFLECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionStep(BaseModel):
    """A single step in the execution plan."""

    step_id: str
    skill: str = Field(description="MCP skill to invoke (e.g., api.discovery, api.executor)")
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    completed: bool = False


class AgentState(BaseModel):
    """
    LangGraph state object shared across the entire agent graph.

    This is the single source of truth during an agent execution run.
    All agents read from and write to this state.
    """

    # Conversation context
    session_id: str
    user_id: str
    conversation_id: str | None = None

    # Input
    user_query: str

    # Execution lifecycle
    status: ExecutionStatus = ExecutionStatus.PENDING
    intent: str | None = None
    plan: list[ExecutionStep] = Field(default_factory=list)
    current_step_index: int = 0

    # Results
    api_method: str | None = None
    api_url: str | None = None
    request_body: dict[str, Any] | None = None
    response_status: int | None = None
    response_body: dict[str, Any] | None = None
    curl_equivalent: str | None = None
    sdk_examples: dict[str, str] | None = None

    # Agent communication
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    reflection_notes: list[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3

    # Error tracking
    error: str | None = None

    # Metadata
    trace_id: str | None = None
    span_id: str | None = None
