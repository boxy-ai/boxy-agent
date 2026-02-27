from __future__ import annotations

from boxy_agent.main_agent.orchestration import (
    ActionCall,
    CompletionGateInput,
    TodoItem,
    ToolCandidate,
    evaluate_completion_gate,
    pick_single_action_call,
    should_replan,
    to_openai_tool_name,
    top_k_tools,
)


def test_should_replan_is_sparse() -> None:
    assert should_replan(iteration=0, previous_step_failed=False, todo_blocked=False) is True
    assert should_replan(iteration=2, previous_step_failed=True, todo_blocked=False) is True
    assert should_replan(iteration=2, previous_step_failed=False, todo_blocked=True) is True
    assert should_replan(iteration=2, previous_step_failed=False, todo_blocked=False) is False


def test_tool_name_is_openai_compatible_and_bounded() -> None:
    name = to_openai_tool_name("dq", "gmail.messages.search")
    assert name == "dq__gmail_messages_search"

    long_name = to_openai_tool_name("bt", "x" * 200)
    assert len(long_name) <= 64
    assert long_name.startswith("bt__")


def test_top_k_tools_filters_by_category_and_uses_recency_boost() -> None:
    tools = [
        ToolCandidate(
            name="dq__gmail_messages",
            capability_name="gmail.messages",
            category="data_query",
            description="List gmail messages",
        ),
        ToolCandidate(
            name="dq__calendar_events",
            capability_name="calendar.events",
            category="data_query",
            description="List calendar events",
        ),
        ToolCandidate(
            name="bt__gmail_send",
            capability_name="gmail.send",
            category="boxy_tool",
            description="Send gmail message",
        ),
    ]

    ranked = top_k_tools(
        query_text="send email to alex",
        category="data_query",
        tools=tools,
        k=2,
        recent_calls={"dq__calendar_events": 3},
    )

    assert [tool.name for tool in ranked] == ["dq__calendar_events", "dq__gmail_messages"]


def test_pick_single_action_call_rejects_multiple_actions() -> None:
    calls = [
        ActionCall(name="bt__gmail_send", arguments={"to": ["a@example.com"]}),
        ActionCall(name="bt__gmail_archive", arguments={"id": "m1"}),
    ]
    result = pick_single_action_call(calls)
    assert result.error == "multiple_action_calls"
    assert result.call is None


def test_pick_single_action_call_accepts_single_action() -> None:
    calls = [ActionCall(name="dq__gmail_messages", arguments={"limit": 5})]
    result = pick_single_action_call(calls)
    assert result.error is None
    assert result.call is not None
    assert result.call.name == "dq__gmail_messages"


def test_completion_gate_rejects_success_without_evidence_or_pending_todos() -> None:
    decision = evaluate_completion_gate(
        CompletionGateInput(
            status="success",
            evidence_refs=[],
            todo_list=[
                TodoItem(id="1", title="send", status="done"),
                TodoItem(id="2", title="log", status="pending"),
            ],
            side_effect_executed=True,
        )
    )
    assert decision.accepted is False
    assert decision.reason == "pending_todos"

    decision = evaluate_completion_gate(
        CompletionGateInput(
            status="success",
            evidence_refs=[],
            todo_list=[TodoItem(id="1", title="send", status="done")],
            side_effect_executed=True,
        )
    )
    assert decision.accepted is False
    assert decision.reason == "missing_evidence"


def test_completion_gate_accepts_valid_success() -> None:
    decision = evaluate_completion_gate(
        CompletionGateInput(
            status="success",
            evidence_refs=["message_id:123"],
            todo_list=[TodoItem(id="1", title="send", status="done")],
            side_effect_executed=True,
            known_evidence_refs={"message_id:123"},
        )
    )
    assert decision.accepted is True
    assert decision.reason is None


def test_completion_gate_rejects_unknown_evidence_refs() -> None:
    decision = evaluate_completion_gate(
        CompletionGateInput(
            status="success",
            evidence_refs=["message_id:999"],
            todo_list=[TodoItem(id="1", title="send", status="done")],
            side_effect_executed=True,
            known_evidence_refs={"message_id:123"},
        )
    )
    assert decision.accepted is False
    assert decision.reason == "unknown_evidence"
