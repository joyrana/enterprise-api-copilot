"""Compatibility shim for legacy `agents.memory.agent` imports."""

from ai.memory.agent import memory_read_node, memory_write_node

__all__ = ["memory_read_node", "memory_write_node"]
