"""Completion gating for the built-in main agent."""

from __future__ import annotations

import json
from typing import cast

from boxy_agent.models import AgentResult
from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.sdk import control, memory, tracing
from boxy_agent.types import JsonValue

from .helpers import (
    JsonObject,
    chat_complete,
    known_evidence_refs,
    parse_tool_calls,
    pop_pending_completion,
)
from .orchestration import (
    CompletionGateInput,
    CompletionStatus,
    TodoItem,
    evaluate_completion_gate,
    pick_single_action_call,
)


def call_complete_task(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    model: str,
    termination_key: str,
    allowed_statuses: set[str],
    task_state: JsonObject,
    todo_list: list[TodoItem],
    observation: JsonObject,
    todo_list_json: list[JsonObject],
) -> AgentResult | None:
    pending = pop_pending_completion(exec_ctx)
    if pending is None:
        request = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "If task can end, call complete tool with status/reason "
                        "and optional evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "observation": observation,
                            "task_state": task_state,
                            "todo_list": todo_list_json,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "sys__complete_task",
                        "description": "Complete the task",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "success",
                                        "failed",
                                        "cancelled",
                                        "need_user_input",
                                        "waiting_external",
                                    ],
                                },
                                "reason": {"type": "string"},
                                "user_facing_summary": {"type": "string"},
                                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["status", "reason"],
                        },
                    },
                }
            ],
            "tool_choice": "required",
        }
        try:
            response = chat_complete(exec_ctx, cast(JsonObject, request))
            calls = parse_tool_calls(response)
            selection = pick_single_action_call(calls)
            if selection.call is None:
                return None
            pending = selection.call.arguments
        except Exception:  # noqa: BLE001
            return None

    status = pending.get("status")
    reason = pending.get("reason")
    evidence_refs = pending.get("evidence_refs")
    if not isinstance(status, str) or status not in allowed_statuses:
        return None
    if not isinstance(reason, str):
        return None
    evidence = (
        [value for value in evidence_refs if isinstance(value, str)]
        if isinstance(evidence_refs, list)
        else []
    )
    known_refs = known_evidence_refs(task_state)

    decision = evaluate_completion_gate(
        CompletionGateInput(
            status=cast(CompletionStatus, status),
            evidence_refs=evidence,
            todo_list=todo_list,
            side_effect_executed=bool(task_state.get("side_effect_executed", False)),
            known_evidence_refs=known_refs if known_refs else None,
        )
    )
    tracing.trace(
        exec_ctx,
        "main.completion.gate",
        {
            "status": status,
            "accepted": decision.accepted,
            "reason": decision.reason,
            "evidence_refs": cast(JsonValue, evidence),
        },
    )
    if not decision.accepted:
        return None

    termination = {
        "status": status,
        "reason": reason,
        "user_facing_summary": pending.get("user_facing_summary", ""),
        "evidence_refs": evidence,
    }
    memory.set(exec_ctx, termination_key, termination)
    control.terminate(exec_ctx, reason)
    return AgentResult(output=termination)
