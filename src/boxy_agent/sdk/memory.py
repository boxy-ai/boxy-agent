"""Namespaced memory helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.public_sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["delete", "get", "set"]


def get(exec_ctx: AgentExecutionContext, key: str, scope: str = "session") -> JsonValue | None:
    """Read a memory value."""
    return runtime_bindings(exec_ctx).memory_get(key, scope=scope)


def set(
    exec_ctx: AgentExecutionContext, key: str, value: JsonValue, scope: str = "session"
) -> None:
    """Write a memory value."""
    runtime_bindings(exec_ctx).memory_set(key, value, scope=scope)


def delete(exec_ctx: AgentExecutionContext, key: str, scope: str = "session") -> None:
    """Delete a memory value."""
    runtime_bindings(exec_ctx).memory_delete(key, scope=scope)
