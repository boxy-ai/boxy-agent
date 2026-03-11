from __future__ import annotations

import pytest
from runtime.support import discovered_agent
from test_helpers.capabilities import DEFAULT_DATA_QUERY_NAME, default_capability_catalog

from boxy_agent import AgentCapabilities, AgentResult, query_data, trace
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.errors import (
    AgentExecutionError,
    AgentNotFoundError,
    InvalidEventError,
)
from boxy_agent.runtime.providers import UnconfiguredClientError


def test_runtime_rejects_unknown_agent() -> None:
    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {},
    )

    with pytest.raises(AgentNotFoundError):
        runtime.run("missing", {"type": "start"})


def test_runtime_rejects_invalid_event_payload() -> None:
    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main", handler=lambda _context: AgentResult(output={"ok": True})
            )
        },
    )

    with pytest.raises(InvalidEventError):
        runtime.run("main", {"type": "start", "payload": []})

    with pytest.raises(InvalidEventError, match="payload keys"):
        runtime.run("main", {"type": "start", "payload": {"": 1}})


def test_runtime_records_trace_calls() -> None:
    def handle(context):
        trace(context, "custom", {"x": 1})
        return AgentResult(output={"ok": True})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {"main": discovered_agent(name="main", handler=handle)},
    )

    report = runtime.run("main", {"type": "start"})

    assert any(item.trace_name == "custom" for item in report.traces)


def test_automation_agent_context_has_no_delegation_api() -> None:
    def handle(context):
        return AgentResult(output={"has_delegate": hasattr(context, "delegate_to_agent")})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {"worker": discovered_agent(name="worker", handler=handle)},
    )

    report = runtime.run("worker", {"type": "start"})
    assert report.last_output == {"has_delegate": False}


def test_runtime_rejects_queue_event_without_source() -> None:
    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {},
    )

    with pytest.raises(ValueError, match="source"):
        runtime.queue_event({"type": "connector.email"}, source=" ")


def test_runtime_accepts_external_queued_event() -> None:
    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {},
    )

    runtime.queue_event({"type": "connector.email", "payload": {"id": "m-1"}}, source="connector")
    queued = runtime.drain_event_queue()

    assert len(queued) == 1
    assert queued[0].source == "connector"
    assert queued[0].event.type == "connector.email"


def test_runtime_wraps_unexpected_handler_failures() -> None:
    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(name="main", handler=lambda _context: 1 / 0)
        },
    )

    with pytest.raises(AgentExecutionError, match="Agent handler raised an exception"):
        runtime.run("main", {"type": "start"})


def test_runtime_does_not_wrap_unconfigured_client_errors() -> None:
    def handle(context):
        query_data(context, DEFAULT_DATA_QUERY_NAME, {"chat_id": "chat-1"})
        return AgentResult(output={"ok": True})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(data_queries=frozenset({DEFAULT_DATA_QUERY_NAME})),
            )
        },
    )

    with pytest.raises(UnconfiguredClientError):
        runtime.run("main", {"type": "start"})
