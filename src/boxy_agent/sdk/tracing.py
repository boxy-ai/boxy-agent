"""Namespaced tracing helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["trace"]


def trace(
    exec_ctx: AgentExecutionContext,
    name: str,
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Emit a structured trace record."""
    runtime_bindings(exec_ctx).trace(name, payload)
