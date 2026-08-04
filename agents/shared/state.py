"""Compatibility shim for legacy `agents.shared.state` imports."""

from ai.shared.state import AgentState, ExecutionStatus, ExecutionStep

__all__ = ["AgentState", "ExecutionStatus", "ExecutionStep"]
