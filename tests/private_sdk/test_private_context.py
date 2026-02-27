from __future__ import annotations

from boxy_agent import (
    AgentCapabilities,
    AgentEvent,
    DataQueryDescriptor,
    PrivateAgentExecutionContext,
    ToolDescriptor,
)
from boxy_agent.private_sdk import DelegateResult
from boxy_agent.runtime.models import InstalledAgent
from boxy_agent.types import JsonValue


class _FakePrivateBindings:
    def __init__(
        self,
        *,
        installed_agents: list[InstalledAgent],
        terminated_result: bool,
        terminated_reasons: list[str | None],
    ) -> None:
        self._installed_agents = installed_agents
        self._terminated_result = terminated_result
        self._terminated_reasons = terminated_reasons

    def llm_chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {"echo": request}

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        return []

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        raise AssertionError(f"unexpected query_data call: {name}")

    def list_boxy_tools(self) -> list[ToolDescriptor]:
        return []

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError(f"unexpected call_boxy_tool call: {name}")

    def list_builtin_tools(self) -> list[ToolDescriptor]:
        return []

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError(f"unexpected call_builtin_tool call: {name}")

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        return None

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        pass

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        pass

    def trace(self, name: str, payload: dict[str, JsonValue] | None = None) -> None:
        pass

    def terminate(self, reason: str | None = None) -> None:
        self._terminated_reasons.append(reason)

    def emit_event(self, event: AgentEvent) -> None:
        pass

    def list_agents(self) -> list[InstalledAgent]:
        return self._installed_agents

    def delegate_to_agent(
        self,
        agent_name: str,
        event: AgentEvent,
    ) -> DelegateResult:
        if self._terminated_result:
            self.terminate("delegated_terminated")
        return DelegateResult(
            output={"ok": True, "agent": agent_name, "event_type": event.type},
            terminated=self._terminated_result,
        )


def _private_context(
    *,
    terminated_result: bool,
) -> tuple[PrivateAgentExecutionContext, list[str | None]]:
    terminated_reasons: list[str | None] = []

    installed_agents = [
        InstalledAgent(
            name="main",
            description="Main agent",
            version="1.0.0",
            agent_type="main",
            expected_event_types=("start",),
            capabilities=AgentCapabilities(),
        ),
        InstalledAgent(
            name="sub",
            description="Sub agent",
            version="1.0.0",
            agent_type="automation",
            expected_event_types=("subtask",),
            capabilities=AgentCapabilities(),
        ),
    ]

    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start"),
        session_id="s-1",
        agent_name="main",
        _runtime=_FakePrivateBindings(
            installed_agents=installed_agents,
            terminated_result=terminated_result,
            terminated_reasons=terminated_reasons,
        ),
    )
    return context, terminated_reasons


def test_private_context_lists_installed_agents() -> None:
    context, _ = _private_context(terminated_result=False)
    names = [item.name for item in context.list_agents()]
    assert names == ["main", "sub"]


def test_private_context_delegation_terminates_when_delegate_terminated() -> None:
    context, terminated_reasons = _private_context(terminated_result=True)
    result = context.delegate_to_agent("sub", AgentEvent(type="subtask"))

    assert result.output == {"ok": True, "agent": "sub", "event_type": "subtask"}
    assert result.terminated is True
    assert terminated_reasons == ["delegated_terminated"]
