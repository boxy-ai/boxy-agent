from __future__ import annotations

import json

from boxy_agent.main_agent.agent import handle
from boxy_agent.main_agent.execution import collect_candidates
from boxy_agent.models import AgentCapabilities, AgentEvent, DataQueryDescriptor, ToolDescriptor
from boxy_agent.private_sdk import DelegateResult
from boxy_agent.private_sdk.interfaces import PrivateAgentExecutionContext
from boxy_agent.runtime.models import InstalledAgent
from boxy_agent.types import JsonValue


class _FakeBindings:
    def __init__(self, llm_responses: list[dict[str, JsonValue]]) -> None:
        self._llm_responses = llm_responses
        self._memory: dict[tuple[str, str], JsonValue] = {}
        self.terminated: list[str | None] = []

    def llm_chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _ = request
        if not self._llm_responses:
            raise AssertionError("unexpected extra llm call")
        return self._llm_responses.pop(0)

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        return [DataQueryDescriptor(name="gmail.messages", description="List gmail messages")]

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        _ = params
        if name != "gmail.messages":
            raise AssertionError(f"unexpected query name: {name}")
        return [{"id": "m1"}]

    def list_boxy_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="gmail.send_message", description="Send")]

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        _ = params
        if name != "gmail.send_message":
            raise AssertionError(f"unexpected boxy tool: {name}")
        return {"status": "sent", "evidence_refs": ["message_id:out-1"]}

    def list_builtin_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="web_search", description="Search")]

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        _ = params
        if name != "web_search":
            raise AssertionError(f"unexpected built-in tool: {name}")
        return {"results": []}

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        return self._memory.get((scope, key))

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        self._memory[(scope, key)] = value

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        self._memory.pop((scope, key), None)

    def trace(
        self,
        name: str,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        _ = name, payload

    def terminate(self, reason: str | None = None) -> None:
        self.terminated.append(reason)

    def emit_event(self, event: AgentEvent) -> None:
        _ = event

    def list_agents(self) -> list[InstalledAgent]:
        return [
            InstalledAgent(
                name="auto-agent",
                description="automation",
                version="1.0.0",
                agent_type="automation",
                expected_event_types=("delegated.task",),
                capabilities=AgentCapabilities(),
            )
        ]

    def delegate_to_agent(self, agent_name: str, event: AgentEvent) -> DelegateResult:
        _ = agent_name, event
        return DelegateResult(output={"ok": True}, terminated=False)


class _NoAutomationBindings(_FakeBindings):
    def list_agents(self) -> list[InstalledAgent]:
        return []


class _NoEvidenceBindings(_FakeBindings):
    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        _ = params
        if name != "gmail.send_message":
            raise AssertionError(f"unexpected boxy tool: {name}")
        return {"status": "sent"}


class _CollisionBindings(_FakeBindings):
    def list_data_queries(self) -> list[DataQueryDescriptor]:
        return [
            DataQueryDescriptor(name="foo", description="one"),
            DataQueryDescriptor(name="foo_3", description="two"),
            DataQueryDescriptor(name="foo", description="three"),
        ]

    def list_boxy_tools(self) -> list[ToolDescriptor]:
        return []

    def list_builtin_tools(self) -> list[ToolDescriptor]:
        return []


def _tool_call(name: str, args: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ]
                }
            }
        ]
    }


def test_main_agent_can_query_then_complete() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "data_query"}),
        _tool_call("dq__gmail_messages", {"limit": 1}),
        _tool_call("sys__complete_task", {"status": "success", "reason": "done"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "success"
    assert bindings.terminated == ["done"]
    task_state = bindings.memory_get("main.task_state")
    assert isinstance(task_state, dict)
    recent_calls = task_state.get("recent_calls")
    assert isinstance(recent_calls, dict)
    assert recent_calls.get("dq__gmail_messages") == 1


def test_main_agent_completion_gate_rejects_success_without_evidence_for_side_effect() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "boxy_tool"}),
        _tool_call("bt__gmail_send_message", {"to": ["a@example.com"]}),
        _tool_call("sys__complete_task", {"status": "success", "reason": "done"}),
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call(
            "sys__complete_task",
            {"status": "failed", "reason": "missing evidence"},
        ),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["missing evidence"]


def test_main_agent_completion_gate_rejects_unknown_evidence_ref() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "boxy_tool"}),
        _tool_call("bt__gmail_send_message", {"to": ["a@example.com"]}),
        _tool_call(
            "sys__complete_task",
            {"status": "success", "reason": "done", "evidence_refs": ["message_id:unknown"]},
        ),
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "failed", "reason": "evidence mismatch"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["evidence mismatch"]


def test_main_agent_delegate_failure_sets_previous_step_failed() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "delegate"}),
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__complete_task", {"status": "failed", "reason": "delegate failed"}),
    ]

    bindings = _NoAutomationBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["delegate failed"]
    task_state = bindings.memory_get("main.task_state")
    assert isinstance(task_state, dict)
    assert task_state.get("previous_step_failed") is True


def test_main_agent_completion_allows_evidence_when_known_set_is_empty() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "boxy_tool"}),
        _tool_call("bt__gmail_send_message", {"to": ["a@example.com"]}),
        _tool_call(
            "sys__complete_task",
            {"status": "success", "reason": "done", "evidence_refs": ["external_ref:abc"]},
        ),
    ]

    bindings = _NoEvidenceBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "success"
    assert bindings.terminated == ["done"]


def test_main_agent_replanner_can_clear_todo_list_with_explicit_empty_list() -> None:
    llm_responses = [
        _tool_call("sys__patch_plan", {"todo_list": []}),
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "success", "reason": "done"}),
    ]

    bindings = _FakeBindings(llm_responses)
    bindings.memory_set(
        "main.todo_list",
        [{"id": "stale-1", "title": "stale task", "status": "pending"}],
    )
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "success"
    assert bindings.terminated == ["done"]


def test_main_agent_rejects_invalid_completion_status() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "done", "reason": "bad status"}),
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "failed", "reason": "invalid status rejected"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["invalid status rejected"]


def test_main_agent_does_not_execute_single_candidate_on_unknown_tool_name() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "data_query"}),
        _tool_call("dq__not_a_real_tool", {"limit": 1}),
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "failed", "reason": "unknown tool rejected"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["unknown tool rejected"]


def test_main_agent_does_not_fuzzy_match_prefix_to_side_effect_tool() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "boxy_tool"}),
        _tool_call("bt__gmail_send", {"to": ["a@example.com"]}),
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "failed", "reason": "prefix match rejected"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["prefix match rejected"]


def test_main_agent_rejects_unknown_suffixed_tool_name() -> None:
    llm_responses = [
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "boxy_tool"}),
        _tool_call("bt__gmail_send_message_99", {"to": ["a@example.com"]}),
        {"choices": [{"message": {"content": "{}"}}]},
        _tool_call("sys__select_action_category", {"category": "complete"}),
        _tool_call("sys__complete_task", {"status": "failed", "reason": "unknown suffix rejected"}),
    ]

    bindings = _FakeBindings(llm_responses)
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    result = handle(context)

    assert isinstance(result.output, dict)
    assert result.output["status"] == "failed"
    assert bindings.terminated == ["unknown suffix rejected"]


def test_collect_candidates_ensures_unique_tool_names_after_suffixing() -> None:
    bindings = _CollisionBindings(llm_responses=[])
    context = PrivateAgentExecutionContext(
        event=AgentEvent(type="start", description="run"),
        session_id="s-1",
        agent_name="boxy-main-agent",
        _runtime=bindings,
    )

    candidates = collect_candidates(context)
    names = [item.name for item in candidates]
    assert len(names) == 3
    assert len(set(names)) == 3
