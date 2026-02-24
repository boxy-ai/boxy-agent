from __future__ import annotations

import pytest
from test_helpers.capabilities import (
    boxy_tool_registry,
    builtin_tool_registry,
    data_query_registry,
)

from boxy_agent.runtime.errors import CapabilityViolationError
from boxy_agent.sdk import (
    boxy_tools,
    builtin_tools,
    control,
    data_queries,
    events,
    llm,
    memory,
    models,
    tracing,
)
from boxy_agent.types import JsonValue


class _FakeBindings:
    def __init__(self) -> None:
        self._session_memory: dict[str, JsonValue] = {}
        self._persistent_memory: dict[str, JsonValue] = {}
        self.trace_records: list[tuple[str, dict[str, JsonValue]]] = []
        self.terminated: list[str | None] = []
        self.emitted_events: list[models.AgentEvent] = []

    def llm_complete(self, prompt: str, model: str | None = None) -> str:
        return f"hello::{model or 'default'}::{prompt}"

    def list_data_queries(self):
        return [data_query_registry()["gmail.messages"]]

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        if name != "gmail.messages":
            raise CapabilityViolationError(f"forbidden query: {name}")
        return [{"id": "m-1", "params": params}]

    def list_boxy_tools(self):
        return [boxy_tool_registry()["gmail.send_message"]]

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        if name != "gmail.send_message":
            raise CapabilityViolationError(f"forbidden boxy tool: {name}")
        return {"ok": True, "params": params}

    def list_builtin_tools(self):
        return [builtin_tool_registry()["web_search"]]

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        if name != "web_search":
            raise CapabilityViolationError(f"forbidden built-in tool: {name}")
        return {"items": [], "params": params}

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        if scope == "session":
            return self._session_memory.get(key)
        if scope == "persistent":
            return self._persistent_memory.get(key)
        raise ValueError("scope must be either 'session' or 'persistent'")

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        if scope == "session":
            self._session_memory[key] = value
            return
        if scope == "persistent":
            self._persistent_memory[key] = value
            return
        raise ValueError("scope must be either 'session' or 'persistent'")

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        if scope == "session":
            self._session_memory.pop(key, None)
            return
        if scope == "persistent":
            self._persistent_memory.pop(key, None)
            return
        raise ValueError("scope must be either 'session' or 'persistent'")

    def trace(self, name: str, payload: dict[str, JsonValue] | None = None) -> None:
        self.trace_records.append((name, payload or {}))

    def terminate(self, reason: str | None = None) -> None:
        self.terminated.append(reason)

    def emit_event(self, event: models.AgentEvent) -> None:
        self.emitted_events.append(event)


def test_context_routes_calls_through_sdk_helpers() -> None:
    bindings = _FakeBindings()
    context = models.AgentExecutionContext(
        event=models.AgentEvent(type="start", description="Start", payload={}),
        session_id="session-1",
        agent_name="agent-a",
        _runtime=bindings,
    )

    assert [item.name for item in data_queries.list_available(context)] == ["gmail.messages"]
    assert data_queries.query(context, "gmail.messages", {"fts": "project"}) == [
        {"id": "m-1", "params": {"fts": "project"}}
    ]
    with pytest.raises(CapabilityViolationError):
        data_queries.query(context, "calendar.events", {})

    assert [item.name for item in boxy_tools.list_available(context)] == ["gmail.send_message"]
    assert boxy_tools.call(context, "gmail.send_message", {"to": "a@example.com"}) == {
        "ok": True,
        "params": {"to": "a@example.com"},
    }
    with pytest.raises(CapabilityViolationError):
        boxy_tools.call(context, "calendar.create_event", {})

    assert [item.name for item in builtin_tools.list_available(context)] == ["web_search"]
    assert builtin_tools.call(context, "web_search", {"query": "boxy"}) == {
        "items": [],
        "params": {"query": "boxy"},
    }

    assert llm.complete(context, "Summarize") == "hello::default::Summarize"

    memory.set(context, "k", {"v": 1})
    assert memory.get(context, "k") == {"v": 1}
    memory.delete(context, "k")
    assert memory.get(context, "k") is None

    tracing.trace(context, "step.custom", {"a": 1})
    assert bindings.trace_records == [("step.custom", {"a": 1})]

    events.emit(context, "insight.generated", description="ready", payload={"a": 1})
    assert [item.type for item in bindings.emitted_events] == ["insight.generated"]

    control.terminate(context, "done")
    assert bindings.terminated == ["done"]
