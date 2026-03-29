"""Client and memory primitives used by runtime providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from boxy_agent.models import DataQueryDescriptor, ToolDescriptor
from boxy_agent.runtime.errors import AgentRuntimeError
from boxy_agent.sdk.interfaces import DataQueryClient, LlmClient, MemoryStore, ToolClient
from boxy_agent.types import JsonValue


class UnconfiguredClientError(AgentRuntimeError):
    """Raised when a runtime client is used without a configured implementation."""


class BuiltinToolError(AgentRuntimeError):
    """Raised when a built-in tool execution fails."""


class UnconfiguredLlmClient(LlmClient):
    """LLM client placeholder that requires explicit runtime injection."""

    def chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _ = request
        # TODO(boxy-agent): add an optional BYOK OpenRouter-backed LLM client for local SDK tests.
        raise UnconfiguredClientError("No LLM client configured")


class StaticDataQueryClient(DataQueryClient):
    """Static data query client with explicit canned responses."""

    def __init__(
        self,
        *,
        descriptors: Sequence[DataQueryDescriptor] | None = None,
        query_results: Mapping[str, JsonValue] | None = None,
    ) -> None:
        source_descriptors = descriptors or []
        self._descriptors = {descriptor.name: descriptor for descriptor in source_descriptors}
        self._query_results = dict(query_results or {})

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        return list(self._descriptors.values())

    def query_data(
        self,
        name: str,
        params: dict[str, JsonValue],
        *,
        session_id: str,
        actor_principal: str,
    ) -> JsonValue:
        _ = params, session_id, actor_principal
        if name not in self._query_results:
            raise UnconfiguredClientError(f"No data query result configured for '{name}'")
        return self._query_results[name]


class StaticToolClient(ToolClient):
    """Static tool client with explicit canned execution results."""

    def __init__(
        self,
        *,
        descriptors: Sequence[ToolDescriptor] | None = None,
        execution_results: Mapping[str, JsonValue] | None = None,
    ) -> None:
        source_descriptors = descriptors or []
        self._descriptors = {descriptor.name: descriptor for descriptor in source_descriptors}
        self._execution_results = dict(execution_results or {})

    def list_tools(self) -> list[ToolDescriptor]:
        return list(self._descriptors.values())

    def call_tool(
        self,
        name: str,
        params: dict[str, JsonValue],
        *,
        session_id: str,
        actor_principal: str,
    ) -> JsonValue:
        _ = params, session_id, actor_principal
        if name not in self._execution_results:
            raise UnconfiguredClientError(f"No tool result configured for '{name}'")
        return self._execution_results[name]


class InMemoryMemoryStore(MemoryStore):
    """Session + persistent memory store using in-memory dictionaries."""

    def __init__(
        self,
        *,
        session_backing: dict[str, JsonValue] | None = None,
        persistent_backing: dict[str, JsonValue] | None = None,
    ) -> None:
        self._session_backing = session_backing if session_backing is not None else {}
        self._persistent_backing = persistent_backing if persistent_backing is not None else {}

    def get(self, *, scope: str, key: str) -> JsonValue | None:
        backing = self._backing_for_scope(scope)
        return backing.get(key)

    def set(self, *, scope: str, key: str, value: JsonValue) -> None:
        backing = self._backing_for_scope(scope)
        backing[key] = value

    def delete(self, *, scope: str, key: str) -> None:
        backing = self._backing_for_scope(scope)
        backing.pop(key, None)

    def _backing_for_scope(self, scope: str) -> dict[str, JsonValue]:
        if scope == "session":
            return self._session_backing
        if scope == "persistent":
            return self._persistent_backing
        raise ValueError("scope must be either 'session' or 'persistent'")
