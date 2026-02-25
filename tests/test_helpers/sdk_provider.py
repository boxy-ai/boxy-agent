from __future__ import annotations

import uuid
from collections.abc import Mapping

from test_helpers.capabilities import default_capability_catalog

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import AgentEvent
from boxy_agent.public_sdk.interfaces import DataQueryClient, LlmClient, MemoryStore, ToolClient
from boxy_agent.runtime.models import EventQueueItem
from boxy_agent.runtime.providers import (
    InMemoryMemoryStore,
    StaticDataQueryClient,
    StaticToolClient,
)
from boxy_agent.types import JsonValue

DEFAULT_QUERY_RESULTS: dict[str, list[JsonValue]] = {
    "gmail.messages": [
        {
            "id": "msg-1",
            "subject": "Status update",
        }
    ]
}

DEFAULT_BOXY_TOOL_RESULTS: dict[str, JsonValue] = {
    "gmail.send_message": {
        "status": "sent",
        "message_id": "out-1",
    }
}

DEFAULT_BUILTIN_TOOL_RESULTS: dict[str, JsonValue] = {
    "web_search": {
        "items": [],
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

    def complete(self, prompt: str, model: str | None = None) -> str:
        return f"{self._static_response}::{model or 'default'}::{prompt}"


def default_data_query_client(
    *,
    catalog: CapabilityCatalog | None = None,
    query_results: Mapping[str, list[JsonValue]] | None = None,
) -> StaticDataQueryClient:
    active_catalog = catalog or default_capability_catalog()
    resolved_results: dict[str, list[JsonValue]] = {
        name: list(rows) for name, rows in DEFAULT_QUERY_RESULTS.items()
    }
    for name, rows in (query_results or {}).items():
        resolved_results[name] = list(rows)
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

    def llm_client(self) -> LlmClient:
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
