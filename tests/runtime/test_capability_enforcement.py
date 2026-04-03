from __future__ import annotations

import json
from typing import Any, cast

import pytest
from runtime.support import discovered_agent
from test_helpers.capabilities import (
    DEFAULT_BOXY_TOOL_NAME,
    DEFAULT_BUILTIN_TOOL_NAME,
    DEFAULT_DATA_QUERY_NAME,
    default_capability_catalog,
)
from test_helpers.sdk_provider import MockAgentSdkProvider

from boxy_agent import (
    AgentCapabilities,
    AgentResult,
    call_boxy_tool,
    emit_event,
    list_boxy_tools,
    list_builtin_tools,
    list_data_queries,
    query_data,
)
from boxy_agent.capabilities import CapabilityCatalog, load_capability_catalog_from_text
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.errors import (
    AgentExecutionError,
    CapabilitySchemaError,
    CapabilityViolationError,
    RegistrationError,
)
from boxy_agent.runtime.providers import StaticDataQueryClient, StaticToolClient
from boxy_agent.sdk import llm as llm_sdk
from boxy_agent.types import JsonValue

READ_ONLY_BOXY_TOOL_NAME = "google_gmail.gmail_search_threads"


def _runtime_with_default_catalog(**kwargs) -> AgentRuntime:
    capability_catalog = kwargs.pop("capability_catalog", default_capability_catalog())
    data_client = kwargs.pop("data_client", None)
    boxy_tool_client = kwargs.pop("boxy_tool_client", None)
    builtin_tool_client = kwargs.pop("builtin_tool_client", None)
    llm_client = kwargs.pop("llm_client", None)
    sdk_provider = kwargs.pop("sdk_provider", None)
    if sdk_provider is None and any(
        value is not None
        for value in (data_client, boxy_tool_client, builtin_tool_client, llm_client)
    ):
        sdk_provider = MockAgentSdkProvider(
            data_client=data_client,
            boxy_tool_client=boxy_tool_client,
            builtin_tool_client=builtin_tool_client,
            llm_client=llm_client,
        )
    if sdk_provider is not None:
        kwargs["sdk_provider"] = sdk_provider
    return AgentRuntime(capability_catalog=capability_catalog, **kwargs)


def _default_query_params() -> dict[str, JsonValue]:
    return {"chat_jid": "chat-1"}


def _default_query_rows() -> dict[str, JsonValue]:
    return {
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
                    "text": "hello",
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


def _default_tool_params() -> dict[str, JsonValue]:
    return {
        "target": "chat-1",
        "message_content": "Hello",
        "idempotency_key": "idemp-1",
    }


def _default_tool_result() -> dict[str, JsonValue]:
    return {
        "status": "sent",
        "target_resolved": "chat-1",
        "message_ref": "msg-1",
        "sent_at": "2026-01-01T00:00:00Z",
        "data": {},
    }


class _RecordingToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, JsonValue]]] = []

    def list_tools(self):
        return []

    def call_tool(
        self,
        name: str,
        params: dict[str, JsonValue],
        *,
        session_id: str,
        actor_principal: str,
    ) -> dict[str, JsonValue]:
        self.calls.append((name, session_id, actor_principal, dict(params)))
        return _default_tool_result()


class _RecordingDataQueryClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, JsonValue]]] = []

    def list_data_queries(self):
        return []

    def query_data(
        self,
        name: str,
        params: dict[str, JsonValue],
        *,
        session_id: str,
        actor_principal: str,
    ):
        self.calls.append((name, session_id, actor_principal, dict(params)))
        return _default_query_rows()


class _LegacyCompleteOnlyLlm:
    pass


def test_runtime_rejects_unauthorized_data_query() -> None:
    def handle(context):
        query_data(context, "forbidden.query", {})
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({DEFAULT_DATA_QUERY_NAME}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilityViolationError):
        runtime.run("main", {"type": "start"})


def test_runtime_passes_session_scope_to_data_query_client_when_supported() -> None:
    data_client = _RecordingDataQueryClient()

    def handle(context):
        rows = query_data(context, DEFAULT_DATA_QUERY_NAME, _default_query_params())
        return AgentResult(output={"rows": rows})

    runtime = _runtime_with_default_catalog(
        data_client=data_client,
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({DEFAULT_DATA_QUERY_NAME}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {"rows": _default_query_rows()}
    assert len(data_client.calls) == 1
    name, session_id, actor_principal, params = data_client.calls[0]
    assert name == DEFAULT_DATA_QUERY_NAME
    assert session_id == report.session_id
    assert actor_principal == f"agent:main:session:{report.session_id}"
    assert params == _default_query_params()


def test_runtime_rejects_unauthorized_boxy_tool() -> None:
    def handle(context):
        call_boxy_tool(context, "forbidden.tool", {})
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilityViolationError):
        runtime.run("main", {"type": "start"})


def test_runtime_rejects_data_mining_with_side_effecting_boxy_tools() -> None:
    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "miner": discovered_agent(
                name="miner",
                handler=lambda _context: AgentResult(output={"ok": True}),
                agent_type="data_mining",
                expected_event_types=(),
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(
        RegistrationError,
        match=f"side-effecting boxy_tools: {DEFAULT_BOXY_TOOL_NAME}",
    ):
        runtime.list_installed_agents()


def test_runtime_allows_data_mining_with_read_only_boxy_tools() -> None:
    def handle(context):
        result = call_boxy_tool(context, READ_ONLY_BOXY_TOOL_NAME, {"account_id": "acct-1"})
        return AgentResult(output=cast(dict[str, JsonValue], result))

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "miner": discovered_agent(
                name="miner",
                handler=handle,
                agent_type="data_mining",
                expected_event_types=(),
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({READ_ONLY_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        sdk_provider=MockAgentSdkProvider(
            boxy_tool_client=StaticToolClient(
                descriptors=[
                    default_capability_catalog().boxy_tools[READ_ONLY_BOXY_TOOL_NAME],
                ],
                execution_results={
                    READ_ONLY_BOXY_TOOL_NAME: {
                        "data": {
                            "threads": [],
                        },
                        "page_info": {
                            "next_page_token": None,
                        },
                        "resolution": {
                            "account_id": "acct-1",
                        },
                    }
                },
            )
        ),
    )

    report = runtime.run("miner", {"type": "scheduled.interval"})

    assert report.last_output == {
        "data": {
            "threads": [],
        },
        "page_info": {
            "next_page_token": None,
        },
        "resolution": {
            "account_id": "acct-1",
        },
    }


def test_runtime_requires_capability_catalog() -> None:
    def handle(context):
        query_data(context, DEFAULT_DATA_QUERY_NAME, _default_query_params())
        return AgentResult(output={"ok": True})

    invalid_catalog = cast(CapabilityCatalog, None)
    with pytest.raises(ValueError, match="capability_catalog is required"):
        AgentRuntime(
            capability_catalog=invalid_catalog,
            agent_registry_loader=lambda: {
                "main": discovered_agent(
                    name="main",
                    handler=handle,
                    capabilities=AgentCapabilities(
                        data_queries=frozenset({DEFAULT_DATA_QUERY_NAME}),
                        boxy_tools=frozenset(),
                        builtin_tools=frozenset(),
                    ),
                )
            },
        )


def test_runtime_filters_discovery_by_capabilities() -> None:
    def handle(context):
        return AgentResult(
            output={
                "data": [item.name for item in list_data_queries(context)],
                "boxy": [item.name for item in list_boxy_tools(context)],
                "builtin": [item.name for item in list_builtin_tools(context)],
            }
        )

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({DEFAULT_DATA_QUERY_NAME}),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset({DEFAULT_BUILTIN_TOOL_NAME}),
                ),
            )
        }
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {
        "data": [DEFAULT_DATA_QUERY_NAME],
        "boxy": [DEFAULT_BOXY_TOOL_NAME],
        "builtin": [DEFAULT_BUILTIN_TOOL_NAME],
    }


def test_runtime_filters_discovery_by_live_provider_descriptors() -> None:
    catalog = load_capability_catalog_from_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_queries": [
                    {
                        "name": "enabled.messages",
                        "description": "Enabled query",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "array", "items": {"type": "object"}},
                    },
                    {
                        "name": "disabled.messages",
                        "description": "Disabled query",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "array", "items": {"type": "object"}},
                    },
                ],
                "boxy_tools": [
                    {
                        "name": "enabled.send",
                        "description": "Enabled tool",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    },
                    {
                        "name": "disabled.send",
                        "description": "Disabled tool",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    },
                ],
                "builtin_tools": [
                    {
                        "name": "enabled.web",
                        "description": "Enabled built-in",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    },
                    {
                        "name": "disabled.web",
                        "description": "Disabled built-in",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    },
                ],
            }
        )
    )

    def handle(context):
        return AgentResult(
            output={
                "data": [item.name for item in list_data_queries(context)],
                "boxy": [item.name for item in list_boxy_tools(context)],
                "builtin": [item.name for item in list_builtin_tools(context)],
            }
        )

    runtime = _runtime_with_default_catalog(
        capability_catalog=catalog,
        data_client=StaticDataQueryClient(
            descriptors=[catalog.data_queries["enabled.messages"]],
        ),
        boxy_tool_client=StaticToolClient(
            descriptors=[catalog.boxy_tools["enabled.send"]],
        ),
        builtin_tool_client=StaticToolClient(
            descriptors=[catalog.builtin_tools["enabled.web"]],
        ),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({"enabled.messages", "disabled.messages"}),
                    boxy_tools=frozenset({"enabled.send", "disabled.send"}),
                    builtin_tools=frozenset({"enabled.web", "disabled.web"}),
                ),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {
        "data": ["enabled.messages"],
        "boxy": ["enabled.send"],
        "builtin": ["enabled.web"],
    }


def test_runtime_rejects_invalid_capability_input_schema() -> None:
    def handle(context):
        call_boxy_tool(
            context,
            DEFAULT_BOXY_TOOL_NAME,
            {"target": "chat-1", "message_content": 1, "idempotency_key": "idemp-1"},
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilitySchemaError, match="input"):
        runtime.run("main", {"type": "start"})


def test_runtime_rejects_non_string_capability_param_keys() -> None:
    def handle(context):
        query_data(context, DEFAULT_DATA_QUERY_NAME, {1: "chat-1"})  # type: ignore[dict-item]
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({DEFAULT_DATA_QUERY_NAME}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilitySchemaError, match="params"):
        runtime.run("main", {"type": "start"})


def test_runtime_rejects_invalid_capability_output_schema() -> None:
    def handle(context):
        call_boxy_tool(
            context,
            DEFAULT_BOXY_TOOL_NAME,
            _default_tool_params(),
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        boxy_tool_client=StaticToolClient(
            execution_results={DEFAULT_BOXY_TOOL_NAME: {"status": "delivered"}}
        ),
    )

    with pytest.raises(CapabilitySchemaError, match="output"):
        runtime.run("main", {"type": "start"})


def test_runtime_supports_injected_capability_catalog() -> None:
    catalog = load_capability_catalog_from_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_queries": [
                    {
                        "name": "custom.messages",
                        "description": "Custom query",
                        "input_schema": {
                            "type": "object",
                            "properties": {"fts": {"type": "string"}},
                        },
                        "output_schema": {"type": "array", "items": {"type": "object"}},
                    }
                ],
                "boxy_tools": [
                    {
                        "name": "custom.send",
                        "description": "Custom send",
                        "input_schema": {
                            "type": "object",
                            "properties": {"body": {"type": "string"}},
                        },
                        "output_schema": {"type": "object"},
                    }
                ],
                "builtin_tools": [
                    {
                        "name": "custom.web",
                        "description": "Custom built-in",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                        "output_schema": {"type": "object"},
                    }
                ],
            }
        )
    )

    def handle(context):
        return AgentResult(
            output={
                "queries": [item.name for item in list_data_queries(context)],
                "rows": query_data(context, "custom.messages", {"fts": "alpha"}),
            }
        )

    runtime = _runtime_with_default_catalog(
        capability_catalog=catalog,
        data_client=StaticDataQueryClient(
            descriptors=list(catalog.data_queries.values()),
            query_results={"custom.messages": [{"id": "row-1"}]},
        ),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({"custom.messages"}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})
    assert report.last_output == {"queries": ["custom.messages"], "rows": [{"id": "row-1"}]}


def test_runtime_rejects_unauthorized_event_emission() -> None:
    def handle(exec_ctx):
        emit_event(exec_ctx, "insight.generated", payload={"id": "1"})
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                    event_emitters=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilityViolationError):
        runtime.run("main", {"type": "start"})


def test_runtime_allows_authorized_event_emission() -> None:
    def handle(exec_ctx):
        emit_event(
            exec_ctx,
            "insight.generated",
            description="ready",
            payload={"id": "1"},
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                    event_emitters=frozenset({"insight.generated"}),
                ),
            )
        }
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {"ok": True}
    queued = runtime.drain_event_queue()
    assert [item.event.type for item in queued] == ["insight.generated"]


def test_runtime_scopes_boxy_tool_calls_with_agent_and_session_actor() -> None:
    tool_client = _RecordingToolClient()

    def handle(context):
        call_boxy_tool(
            context,
            DEFAULT_BOXY_TOOL_NAME,
            _default_tool_params(),
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        boxy_tool_client=tool_client,
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "idle"
    assert len(tool_client.calls) == 1
    name, session_id, actor_principal, params = tool_client.calls[0]
    assert name == DEFAULT_BOXY_TOOL_NAME
    assert session_id == report.session_id
    assert params == _default_tool_params()
    assert actor_principal == f"agent:main:session:{report.session_id}"


def test_runtime_passes_session_scope_to_boxy_tool_client_when_supported() -> None:
    tool_client = _RecordingToolClient()

    def handle(context):
        result = call_boxy_tool(
            context,
            DEFAULT_BOXY_TOOL_NAME,
            _default_tool_params(),
        )
        return AgentResult(output={"result": result})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({DEFAULT_BOXY_TOOL_NAME}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        boxy_tool_client=tool_client,
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {"result": _default_tool_result()}
    assert len(tool_client.calls) == 1
    name, session_id, actor_principal, params = tool_client.calls[0]
    assert name == DEFAULT_BOXY_TOOL_NAME
    assert session_id == report.session_id
    assert actor_principal == f"agent:main:session:{report.session_id}"
    assert params == _default_tool_params()


def test_runtime_chat_complete_requires_chat_complete_implementation() -> None:
    def handle(context):
        response = llm_sdk.chat_complete(
            context,
            {
                "model": "gpt-4.1",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        return AgentResult(output=response)

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        },
        llm_client=cast(Any, _LegacyCompleteOnlyLlm()),
    )

    with pytest.raises(AgentExecutionError, match="chat_complete"):
        runtime.run("main", {"type": "start"})


def test_runtime_rejects_invalid_datetime_format_input() -> None:
    catalog = load_capability_catalog_from_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_queries": [
                    {
                        "name": "custom.messages",
                        "description": "Custom query",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "time_range": {
                                    "type": "object",
                                    "properties": {
                                        "start": {"type": "string", "format": "date-time"},
                                        "end": {"type": "string", "format": "date-time"},
                                    },
                                    "required": ["start", "end"],
                                    "additionalProperties": False,
                                }
                            },
                            "required": ["time_range"],
                            "additionalProperties": False,
                        },
                        "output_schema": {"type": "array", "items": {"type": "object"}},
                    }
                ],
                "boxy_tools": [],
                "builtin_tools": [],
            }
        )
    )

    def handle(context):
        query_data(
            context,
            "custom.messages",
            {
                "time_range": {"start": "not-a-datetime", "end": "also-invalid"},
            },
        )
        return AgentResult(output={"ok": True})

    runtime = AgentRuntime(
        capability_catalog=catalog,
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({"custom.messages"}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        },
    )

    with pytest.raises(CapabilitySchemaError, match="date-time"):
        runtime.run("main", {"type": "start"})
