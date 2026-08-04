"""Compatibility shim for legacy `agents.supervisor.agent` imports."""

from ai.supervisor.agent import (
    SUPPORTED_INTENTS,
    UNSUPPORTED_INTENTS,
    route_after_supervisor,
    supervisor_node,
)

__all__ = [
    "SUPPORTED_INTENTS",
    "UNSUPPORTED_INTENTS",
    "supervisor_node",
    "route_after_supervisor",
]
