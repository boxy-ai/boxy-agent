"""Namespaced Boxy tool helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.models import ToolDescriptor
from boxy_agent.public_sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["call", "list_available"]


def list_available(exec_ctx: AgentExecutionContext) -> list[ToolDescriptor]:
    """List discoverable Boxy tools available to the current agent."""
    return runtime_bindings(exec_ctx).list_boxy_tools()


def call(
    exec_ctx: AgentExecutionContext,
    name: str,
    params: dict[str, JsonValue],
) -> JsonValue:
    """Run a capability-checked Boxy tool call."""
    return runtime_bindings(exec_ctx).call_boxy_tool(name, params)
