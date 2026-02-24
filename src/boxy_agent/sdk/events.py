"""Namespaced event queue helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.models import AgentEvent
from boxy_agent.public_sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["emit"]


def emit(
    exec_ctx: AgentExecutionContext,
    event_type: str,
    *,
    description: str = "",
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Queue an outbound event through the runtime."""
    runtime_bindings(exec_ctx).emit_event(
        AgentEvent(
            type=event_type,
            description=description,
            payload=payload or {},
        )
    )
