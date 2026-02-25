"""Core-backed SDK provider implementation."""

from __future__ import annotations

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import AgentEvent
from boxy_agent.public_sdk.interfaces import DataQueryClient, LlmClient, MemoryStore, ToolClient
from boxy_agent.runtime.models import EventQueueItem
from boxy_agent.types import JsonValue

from .builtin_tools import BuiltinToolClient
from .clients import (
    StaticDataQueryClient,
    StaticToolClient,
    UnconfiguredLlmClient,
)
from .protocols import CoreAgentClient


class CoreBackedMemoryStore(MemoryStore):
    """Memory store backed by boxy-core memory APIs."""

    def __init__(self, *, core_client: CoreAgentClient, session_id: str) -> None:
        self._core_client = core_client
        self._session_id = session_id

    def get(self, *, scope: str, key: str) -> JsonValue | None:
        return self._core_client.get_memory(
            scope=scope,
            key=key,
            session_id=_session_id_for_scope(scope=scope, session_id=self._session_id),
        )

    def set(self, *, scope: str, key: str, value: JsonValue) -> None:
        self._core_client.set_memory(
            scope=scope,
            key=key,
            value=value,
            session_id=_session_id_for_scope(scope=scope, session_id=self._session_id),
        )

    def delete(self, *, scope: str, key: str) -> None:
        self._core_client.delete_memory(
            scope=scope,
            key=key,
            session_id=_session_id_for_scope(scope=scope, session_id=self._session_id),
        )


class CoreAgentSdkProvider:
    """Runtime SDK provider backed by boxy-core session, memory, and queue APIs."""

    def __init__(
        self,
        *,
        core_client: CoreAgentClient,
        data_client: DataQueryClient | None = None,
        boxy_tool_client: ToolClient | None = None,
        builtin_tool_client: ToolClient | None = None,
        llm_client: LlmClient | None = None,
        event_topic: str = "default",
    ) -> None:
        if not event_topic.strip():
            raise ValueError("event_topic must be non-empty")
        self._core_client = core_client
        self._data_client = data_client
        self._boxy_tool_client = boxy_tool_client
        self._builtin_tool_client = builtin_tool_client
        self._llm_client = llm_client
        self._event_topic = event_topic.strip()

    def create_session(self, *, agent_name: str, event: AgentEvent) -> str:
        metadata: dict[str, JsonValue] = {
            "agent_name": agent_name,
            "event": {
                "type": event.type,
                "description": event.description,
            },
        }
        return self._core_client.create_session(metadata=metadata)

    def close_session(self, session_id: str) -> None:
        self._core_client.close_session(session_id)

    def data_query_client(self, catalog: CapabilityCatalog) -> DataQueryClient:
        if self._data_client is not None:
            return self._data_client
        return StaticDataQueryClient(descriptors=list(catalog.data_queries.values()))

    def boxy_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        if self._boxy_tool_client is not None:
            return self._boxy_tool_client
        return StaticToolClient(descriptors=list(catalog.boxy_tools.values()))

    def builtin_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        if self._builtin_tool_client is not None:
            return self._builtin_tool_client
        return BuiltinToolClient(descriptors=list(catalog.builtin_tools.values()))

    def llm_client(self) -> LlmClient:
        if self._llm_client is not None:
            return self._llm_client
        return UnconfiguredLlmClient()

    def create_memory_store(self, *, agent_name: str, session_id: str) -> MemoryStore:
        _ = agent_name
        return CoreBackedMemoryStore(core_client=self._core_client, session_id=session_id)

    def publish_event(self, event: EventQueueItem) -> None:
        self._core_client.enqueue_event(_event_payload(event), topic=self._event_topic)


def _session_id_for_scope(*, scope: str, session_id: str) -> str | None:
    if scope == "session":
        return session_id
    if scope == "persistent":
        # Core persistence APIs use `session_id=None` as the persistent-memory namespace.
        return None
    raise ValueError("scope must be either 'session' or 'persistent'")


def _event_payload(event: EventQueueItem) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "event": {
            "type": event.event.type,
            "description": event.event.description,
            "payload": event.event.payload,
        },
        "source": event.source,
    }
    if event.source_agent is not None:
        payload["source_agent"] = event.source_agent
    if event.session_id is not None:
        payload["session_id"] = event.session_id
    return payload
