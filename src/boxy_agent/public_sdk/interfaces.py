"""Public SDK runtime interfaces and canonical execution context object."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from boxy_agent.models import AgentEvent, AgentResult, DataQueryDescriptor, ToolDescriptor
from boxy_agent.types import JsonValue


class DataQueryClient(Protocol):
    """Interface for discoverable Boxy data query operations."""

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        """List discoverable data queries."""
        ...

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        """Execute a Boxy data query."""
        ...


class ToolClient(Protocol):
    """Interface for discoverable tool operations."""

    def list_tools(self) -> list[ToolDescriptor]:
        """List discoverable tools."""
        ...

    def call_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        """Execute a tool call."""
        ...


class LlmClient(Protocol):
    """Interface for LLM completion calls."""

    def complete(self, prompt: str, model: str | None = None) -> str:
        """Return a completion string."""
        ...


class MemoryStore(Protocol):
    """Interface for session and persistent memory storage."""

    def get(self, *, scope: str, key: str) -> JsonValue | None:
        """Read a memory value."""
        ...

    def set(self, *, scope: str, key: str, value: JsonValue) -> None:
        """Persist a memory value."""
        ...

    def delete(self, *, scope: str, key: str) -> None:
        """Delete a memory value."""
        ...


TraceCallback = Callable[[str, dict[str, JsonValue]], None]
TerminateCallback = Callable[[str | None], None]


class RuntimeBindings(Protocol):
    """Opaque runtime-bound capability surface for one execution context invocation."""

    def llm_complete(self, prompt: str, model: str | None = None) -> str:
        """Complete an LLM prompt."""
        ...

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        """List discoverable data queries."""
        ...

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        """Execute a data query."""
        ...

    def list_boxy_tools(self) -> list[ToolDescriptor]:
        """List discoverable Boxy tools."""
        ...

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        """Execute a Boxy tool."""
        ...

    def list_builtin_tools(self) -> list[ToolDescriptor]:
        """List discoverable built-in tools."""
        ...

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        """Execute a built-in tool."""
        ...

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        """Read memory."""
        ...

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        """Write memory."""
        ...

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        """Delete memory."""
        ...

    def trace(self, name: str, payload: dict[str, JsonValue] | None = None) -> None:
        """Emit a trace record."""
        ...

    def terminate(self, reason: str | None = None) -> None:
        """Request termination."""
        ...

    def emit_event(self, event: AgentEvent) -> None:
        """Queue an outbound event."""
        ...


type AgentMainFunction = Callable[["AgentExecutionContext"], AgentResult | JsonValue | None]


@dataclass(kw_only=True)
class AgentExecutionContext:
    """Canonical execution context object passed to an agent main function."""

    event: AgentEvent
    session_id: str
    agent_name: str
    _runtime: RuntimeBindings = field(repr=False, compare=False)


def runtime_bindings(exec_ctx: AgentExecutionContext) -> RuntimeBindings:
    """Return the opaque runtime bindings attached to an execution context."""
    return exec_ctx._runtime
