"""Namespaced Boxy data query helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.models import DataQueryDescriptor
from boxy_agent.sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["list_available", "query"]


def list_available(exec_ctx: AgentExecutionContext) -> list[DataQueryDescriptor]:
    """List discoverable data queries available to the current agent."""
    return runtime_bindings(exec_ctx).list_data_queries()


def query(
    exec_ctx: AgentExecutionContext,
    name: str,
    params: dict[str, JsonValue],
) -> list[JsonValue]:
    """Run a capability-checked Boxy data query."""
    return runtime_bindings(exec_ctx).query_data(name, params)
