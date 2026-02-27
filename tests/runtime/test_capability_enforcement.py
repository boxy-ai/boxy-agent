from __future__ import annotations

from typing import Any, cast

import pytest
from runtime.support import discovered_agent
from test_helpers.capabilities import default_capability_catalog

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
)
from boxy_agent.runtime.providers import StaticDataQueryClient, StaticToolClient
from boxy_agent.sdk import llm as llm_sdk


def _runtime_with_default_catalog(**kwargs) -> AgentRuntime:
    return AgentRuntime(capability_catalog=default_capability_catalog(), **kwargs)


class _ActorAwareToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def list_tools(self):
        return []

    def call_tool(self, name: str, params: dict[str, object]) -> dict[str, object]:
        _ = name, params
        raise AssertionError("runtime should prefer call_tool_with_actor when available")

    def call_tool_with_actor(
        self,
        name: str,
        params: dict[str, object],
        *,
        actor_principal: str,
    ) -> dict[str, object]:
        self.calls.append((name, actor_principal, dict(params)))
        return {"status": "sent", "message_id": "msg-1"}


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
                    data_queries=frozenset({"gmail.messages"}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilityViolationError):
        runtime.run("main", {"type": "start"})


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
                    boxy_tools=frozenset({"gmail.send_message"}),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilityViolationError):
        runtime.run("main", {"type": "start"})


def test_runtime_requires_capability_catalog() -> None:
    def handle(context):
        query_data(context, "gmail.messages", {"fts": "alpha"})
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
                        data_queries=frozenset({"gmail.messages"}),
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
                    data_queries=frozenset({"gmail.messages"}),
                    boxy_tools=frozenset({"gmail.send_message"}),
                    builtin_tools=frozenset({"web_search"}),
                ),
            )
        }
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {
        "data": ["gmail.messages"],
        "boxy": ["gmail.send_message"],
        "builtin": ["web_search"],
    }


def test_runtime_rejects_invalid_capability_input_schema() -> None:
    def handle(context):
        call_boxy_tool(
            context,
            "gmail.send_message",
            {"to": "not-an-array", "subject": "Re: x", "body": "hello"},
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({"gmail.send_message"}),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilitySchemaError, match="input"):
        runtime.run("main", {"type": "start"})


def test_runtime_rejects_non_string_capability_param_keys() -> None:
    def handle(context):
        query_data(context, "gmail.messages", {1: "alpha"})  # type: ignore[dict-item]
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({"gmail.messages"}),
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
            "gmail.send_message",
            {"to": ["a@example.com"], "subject": "Re: x", "body": "hello"},
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({"gmail.send_message"}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        boxy_tool_client=StaticToolClient(
            execution_results={"gmail.send_message": {"status": "sent"}}
        ),
    )

    with pytest.raises(CapabilitySchemaError, match="output"):
        runtime.run("main", {"type": "start"})


def test_runtime_supports_injected_capability_catalog() -> None:
    catalog = load_capability_catalog_from_text(
        """
schema_version = 1

[[data_queries]]
name = "custom.messages"
description = "Custom query"
input_schema = { type = "object", properties = { fts = { type = "string" } } }
output_schema = { type = "array", items = { type = "object" } }

[[boxy_tools]]
name = "custom.send"
description = "Custom send"
input_schema = { type = "object", properties = { body = { type = "string" } } }
output_schema = { type = "object" }

[[builtin_tools]]
name = "custom.web"
description = "Custom built-in"
input_schema = { type = "object", properties = { query = { type = "string" } } }
output_schema = { type = "object" }
""".strip()
    )

    def handle(context):
        return AgentResult(
            output={
                "queries": [item.name for item in list_data_queries(context)],
                "rows": query_data(context, "custom.messages", {"fts": "alpha"}),
            }
        )

    runtime = AgentRuntime(
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
    tool_client = _ActorAwareToolClient()

    def handle(context):
        call_boxy_tool(
            context,
            "gmail.send_message",
            {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"},
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset(),
                    boxy_tools=frozenset({"gmail.send_message"}),
                    builtin_tools=frozenset(),
                ),
            )
        },
        boxy_tool_client=tool_client,
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "idle"
    assert len(tool_client.calls) == 1
    name, actor_principal, params = tool_client.calls[0]
    assert name == "gmail.send_message"
    assert params == {"to": ["a@example.com"], "subject": "Hi", "body": "Hello"}
    assert actor_principal == f"agent:main:session:{report.session_id}"


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
    def handle(context):
        query_data(
            context,
            "gmail.messages",
            {
                "fts": "alpha",
                "time_range": {"start": "not-a-datetime", "end": "also-invalid"},
            },
        )
        return AgentResult(output={"ok": True})

    runtime = _runtime_with_default_catalog(
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    data_queries=frozenset({"gmail.messages"}),
                    boxy_tools=frozenset(),
                    builtin_tools=frozenset(),
                ),
            )
        }
    )

    with pytest.raises(CapabilitySchemaError, match="date-time"):
        runtime.run("main", {"type": "start"})
