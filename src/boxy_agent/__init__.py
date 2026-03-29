"""Top-level SDK facade for Boxy agent authors."""

from __future__ import annotations

from boxy_agent.compiler import (
    CompiledAgent,
    PackagedAgent,
    compile_agent,
    package_agent,
)
from boxy_agent.models import (
    AgentCapabilities,
    AgentEvent,
    AgentMetadata,
    AgentResult,
    DataQueryDescriptor,
    ToolDescriptor,
)
from boxy_agent.sdk.decorators import agent_main
from boxy_agent.sdk.interfaces import AgentExecutionContext
from boxy_agent.types import JsonValue

from . import sdk as sdk
from ._version import __version__

__all__ = [
    "AgentCapabilities",
    "AgentExecutionContext",
    "AgentEvent",
    "AgentMetadata",
    "AgentResult",
    "CompiledAgent",
    "DataQueryDescriptor",
    "PackagedAgent",
    "ToolDescriptor",
    "agent_main",
    "call_boxy_tool",
    "call_builtin_tool",
    "compile_agent",
    "list_boxy_tools",
    "list_builtin_tools",
    "list_data_queries",
    "llm_chat_complete",
    "emit_event",
    "memory_delete",
    "memory_get",
    "memory_set",
    "package_agent",
    "query_data",
    "sdk",
    "terminate",
    "trace",
    "__version__",
]


def llm_chat_complete(
    exec_ctx: AgentExecutionContext,
    request: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Complete a chat request through the configured LLM provider."""
    return sdk.llm.chat_complete(exec_ctx, request)


def list_data_queries(exec_ctx: AgentExecutionContext) -> list[DataQueryDescriptor]:
    """List discoverable data queries available to the current agent."""
    return sdk.data_queries.list_available(exec_ctx)


def query_data(
    exec_ctx: AgentExecutionContext,
    name: str,
    params: dict[str, JsonValue],
) -> JsonValue:
    """Run a capability-checked Boxy data query."""
    return sdk.data_queries.query(exec_ctx, name, params)


def list_boxy_tools(exec_ctx: AgentExecutionContext) -> list[ToolDescriptor]:
    """List discoverable Boxy tools available to the current agent."""
    return sdk.boxy_tools.list_available(exec_ctx)


def call_boxy_tool(
    exec_ctx: AgentExecutionContext,
    name: str,
    params: dict[str, JsonValue],
) -> JsonValue:
    """Run a capability-checked Boxy tool call."""
    return sdk.boxy_tools.call(exec_ctx, name, params)


def list_builtin_tools(exec_ctx: AgentExecutionContext) -> list[ToolDescriptor]:
    """List discoverable built-in tools available to the current agent."""
    return sdk.builtin_tools.list_available(exec_ctx)


def call_builtin_tool(
    exec_ctx: AgentExecutionContext,
    name: str,
    params: dict[str, JsonValue],
) -> JsonValue:
    """Run a capability-checked built-in tool call."""
    return sdk.builtin_tools.call(exec_ctx, name, params)


def memory_get(
    exec_ctx: AgentExecutionContext, key: str, scope: str = "session"
) -> JsonValue | None:
    """Read a memory value."""
    return sdk.memory.get(exec_ctx, key, scope=scope)


def memory_set(
    exec_ctx: AgentExecutionContext, key: str, value: JsonValue, scope: str = "session"
) -> None:
    """Write a memory value."""
    sdk.memory.set(exec_ctx, key, value, scope=scope)


def memory_delete(exec_ctx: AgentExecutionContext, key: str, scope: str = "session") -> None:
    """Delete a memory value."""
    sdk.memory.delete(exec_ctx, key, scope=scope)


def trace(
    exec_ctx: AgentExecutionContext,
    name: str,
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Emit a structured trace record."""
    sdk.tracing.trace(exec_ctx, name, payload)


def terminate(exec_ctx: AgentExecutionContext, reason: str | None = None) -> None:
    """Request session termination after the current step."""
    sdk.control.terminate(exec_ctx, reason)


def emit_event(
    exec_ctx: AgentExecutionContext,
    event_type: str,
    *,
    description: str = "",
    payload: dict[str, JsonValue] | None = None,
) -> None:
    """Queue an outbound event through the runtime event queue."""
    sdk.events.emit(
        exec_ctx,
        event_type,
        description=description,
        payload=payload,
    )
