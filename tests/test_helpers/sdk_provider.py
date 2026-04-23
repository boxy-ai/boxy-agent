from __future__ import annotations

import uuid
from collections.abc import Mapping

from test_helpers.capabilities import (
    DEFAULT_BOXY_TOOL_NAME,
    DEFAULT_BUILTIN_TOOL_NAME,
    DEFAULT_DATA_QUERY_NAME,
    default_capability_catalog,
)

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import AgentEvent
from boxy_agent.runtime.models import EventQueueItem
from boxy_agent.runtime.providers import (
    InMemoryMemoryStore,
    StaticDataQueryClient,
    StaticToolClient,
)
from boxy_agent.sdk.interfaces import DataQueryClient, LlmClient, MemoryStore, ToolClient
from boxy_agent.types import JsonValue

DEFAULT_QUERY_RESULTS: dict[str, JsonValue] = {
    DEFAULT_DATA_QUERY_NAME: {
        "data": {
            "chat_jid": "chat-1",
            "messages": [
                {
                    "chat_jid": "chat-1",
                    "message_id": "msg-1",
                    "from_me": False,
                    "sender_jid": "contact-1",
                    "sender_display_name_hint": "Alex",
                    "timestamp_ms": 1,
                    "text": "Status update",
                    "message_type": "text",
                    "is_deleted": False,
                    "is_edited": False,
                    "first_observed_at_ms": 1,
                    "last_observed_at_ms": 1,
                    "updated_at_ms": 1,
                }
            ],
        },
        "page_info": {
            "has_more": False,
            "returned": 1,
        },
        "resolution": {
            "account_id": "acct-1",
            "target": "chat-1",
        },
    }
}

DEFAULT_BOXY_TOOL_RESULTS: dict[str, JsonValue] = {
    DEFAULT_BOXY_TOOL_NAME: {
        "status": "sent",
        "target_resolved": "chat-1",
        "message_ref": "out-1",
        "sent_at": "2026-01-01T00:00:00Z",
        "data": {},
    }
}

DEFAULT_BUILTIN_TOOL_RESULTS: dict[str, JsonValue] = {
    DEFAULT_BUILTIN_TOOL_NAME: {
        "results": [],
    },
    "python_exec": {
        "result": None,
        "stdout": "",
        "stderr": "",
    },
}


class MockLlmClient(LlmClient):
    def __init__(self, *, static_response: str = "mock-llm-response") -> None:
        self._static_response = static_response

    def chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {"mock": request, "text": self._static_response}

    def chat_complete_stream(
        self,
        request: dict[str, JsonValue],
        on_partial,
    ) -> dict[str, JsonValue]:
        _ = on_partial
        return self.chat_complete(request)


def default_data_query_client(
    *,
    catalog: CapabilityCatalog | None = None,
    query_results: Mapping[str, JsonValue] | None = None,
) -> StaticDataQueryClient:
    active_catalog = catalog or default_capability_catalog()
    resolved_results: dict[str, JsonValue] = dict(DEFAULT_QUERY_RESULTS)
    for name, output in (query_results or {}).items():
        resolved_results[name] = output
    return StaticDataQueryClient(
        descriptors=list(active_catalog.data_queries.values()),
        query_results=resolved_results,
    )


def default_boxy_tool_client(
    *,
    catalog: CapabilityCatalog | None = None,
    execution_results: Mapping[str, JsonValue] | None = None,
) -> StaticToolClient:
    active_catalog = catalog or default_capability_catalog()
    resolved_results: dict[str, JsonValue] = dict(DEFAULT_BOXY_TOOL_RESULTS)
    resolved_results.update(execution_results or {})
    return StaticToolClient(
        descriptors=list(active_catalog.boxy_tools.values()),
        execution_results=resolved_results,
    )


def default_builtin_tool_client(
    *,
    catalog: CapabilityCatalog | None = None,
    execution_results: Mapping[str, JsonValue] | None = None,
) -> StaticToolClient:
    active_catalog = catalog or default_capability_catalog()
    resolved_results: dict[str, JsonValue] = dict(DEFAULT_BUILTIN_TOOL_RESULTS)
    resolved_results.update(execution_results or {})
    return StaticToolClient(
        descriptors=list(active_catalog.builtin_tools.values()),
        execution_results=resolved_results,
    )


class MockAgentSdkProvider:
    """In-process SDK provider for tests."""

    def __init__(
        self,
        *,
        data_client: DataQueryClient | None = None,
        boxy_tool_client: ToolClient | None = None,
        builtin_tool_client: ToolClient | None = None,
        llm_client: LlmClient | None = None,
    ) -> None:
        self._data_client = data_client
        self._boxy_tool_client = boxy_tool_client
        self._builtin_tool_client = builtin_tool_client
        self._llm_client = llm_client
        self._persistent_memory_by_agent: dict[str, dict[str, JsonValue]] = {}

    def create_session(self, *, agent_name: str, event: AgentEvent) -> str:
        _ = agent_name, event
        return uuid.uuid4().hex

    def close_session(self, session_id: str) -> None:
        _ = session_id

    def data_query_client(self, catalog: CapabilityCatalog) -> DataQueryClient:
        if self._data_client is not None:
            return self._data_client
        return default_data_query_client(catalog=catalog)

    def boxy_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        if self._boxy_tool_client is not None:
            return self._boxy_tool_client
        return default_boxy_tool_client(catalog=catalog)

    def builtin_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        if self._builtin_tool_client is not None:
            return self._builtin_tool_client
        return default_builtin_tool_client(catalog=catalog)

    def llm_client(self, *, agent_name: str, session_id: str) -> LlmClient:
        _ = agent_name, session_id
        if self._llm_client is not None:
            return self._llm_client
        return MockLlmClient()

    def create_memory_store(self, *, agent_name: str, session_id: str) -> MemoryStore:
        _ = session_id
        session_memory: dict[str, JsonValue] = {}
        persistent_memory = self._persistent_memory_by_agent.setdefault(agent_name, {})
        return InMemoryMemoryStore(
            session_backing=session_memory,
            persistent_backing=persistent_memory,
        )

    def publish_event(self, event: EventQueueItem) -> None:
        _ = event

    def record_trace(
        self,
        *,
        agent_name: str,
        session_id: str,
        event: AgentEvent,
        trace_name: str,
        payload: dict[str, JsonValue],
    ) -> None:
        _ = agent_name, session_id, event, trace_name, payload
