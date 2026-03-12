"""Provider protocol contracts for runtime SDK integrations."""

from __future__ import annotations

from typing import Protocol

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import AgentEvent
from boxy_agent.runtime.models import EventQueueItem
from boxy_agent.sdk.interfaces import DataQueryClient, LlmClient, MemoryStore, ToolClient
from boxy_agent.types import JsonValue


class CoreAgentClient(Protocol):
    """Subset of boxy-core APIs needed by runtime SDK providers."""

    def create_session(self, *, metadata: JsonValue | None = None) -> str:
        """Create and return a session id."""
        ...

    def close_session(self, session_id: str) -> None:
        """Mark a session as closed."""
        ...

    def set_memory(
        self,
        *,
        scope: str,
        key: str,
        value: JsonValue,
        session_id: str | None = None,
    ) -> None:
        """Persist one memory value."""
        ...

    def get_memory(
        self,
        *,
        scope: str,
        key: str,
        session_id: str | None = None,
    ) -> JsonValue | None:
        """Read one memory value."""
        ...

    def delete_memory(
        self,
        *,
        scope: str,
        key: str,
        session_id: str | None = None,
    ) -> None:
        """Delete one memory value."""
        ...

    def enqueue_event(
        self,
        payload: JsonValue,
        *,
        topic: str = "default",
        available_at: str | None = None,
    ) -> str:
        """Publish one event payload to the core queue."""
        ...


class AgentSdkProvider(Protocol):
    """Injectable provider that supplies runtime SDK dependencies."""

    # TODO(boxy-agent): add a bundled mock connector-backed provider for local end-to-end SDK
    # simulation without a live Boxy Desktop runtime.

    def create_session(self, *, agent_name: str, event: AgentEvent) -> str:
        """Create and return a session id."""
        ...

    def close_session(self, session_id: str) -> None:
        """Finalize a session after one runtime invocation."""
        ...

    def data_query_client(self, catalog: CapabilityCatalog) -> DataQueryClient:
        """Provide a data query client."""
        ...

    def boxy_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        """Provide a Boxy tool client."""
        ...

    def builtin_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        """Provide a built-in tool client."""
        ...

    def llm_client(self, *, agent_name: str, session_id: str) -> LlmClient:
        """Provide an LLM client for one runtime invocation."""
        ...

    def create_memory_store(self, *, agent_name: str, session_id: str) -> MemoryStore:
        """Provide memory storage for one runtime invocation."""
        ...

    def publish_event(self, event: EventQueueItem) -> None:
        """Publish one queued runtime event."""
        ...

    def record_trace(
        self,
        *,
        agent_name: str,
        session_id: str,
        event: AgentEvent,
        trace_name: str,
        payload: dict[str, JsonValue],
    ) -> None:
        """Persist or forward one runtime trace record."""
        ...
