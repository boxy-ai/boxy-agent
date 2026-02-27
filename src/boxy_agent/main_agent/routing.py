"""Routing for the built-in main agent."""

from __future__ import annotations

import json
from typing import cast

from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.sdk import boxy_tools, builtin_tools, data_queries
from boxy_agent.types import JsonValue

from .helpers import (
    JsonObject,
    chat_complete,
    parse_tool_calls,
    set_pending_completion,
    todo_to_json,
)
from .orchestration import TodoItem, pick_single_action_call

_ALLOWED_ROUTE_CATEGORIES = {
    "data_query",
    "boxy_tool",
    "builtin_tool",
    "delegate",
    "complete",
}

_ROUTING_POLICY_PROMPT = (
    "Use tools only. Choose exactly one next action category.\n"
    "Category semantics:\n"
    "- data_query: fetch/read evidence from user data; no side effects.\n"
    "- builtin_tool: use runtime built-ins (for example web_search/python_exec).\n"
    "- boxy_tool: perform connector actions; may cause external side effects.\n"
    "- delegate: hand off objective to automation agents.\n"
    "- complete: only when task is done, failed, cancelled, waiting, or needs user input.\n"
    "Tie-breakers:\n"
    "- Prefer data_query over action tools when evidence is missing.\n"
    "- Prefer builtin_tool before boxy_tool when both can progress safely.\n"
    "- Avoid complete if pending work remains or uncertainty is high.\n"
    "- Choose boxy_tool only when side effects are necessary to make progress."
)


def route_action(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    model: str,
    observation: JsonObject,
    task_state: JsonObject,
    todo_list: list[TodoItem],
) -> str:
    capability_context = _routing_capability_context(exec_ctx)
    route_tools = [
        {
            "type": "function",
            "function": {
                "name": "sys__select_action_category",
                "description": "Select the next action category and explain why briefly",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "oneOf": [
                                {
                                    "const": "data_query",
                                    "description": "Fetch evidence by querying user data.",
                                },
                                {
                                    "const": "boxy_tool",
                                    "description": "Use connector tool actions with side effects.",
                                },
                                {
                                    "const": "builtin_tool",
                                    "description": "Use built-in tools such as web search.",
                                },
                                {
                                    "const": "delegate",
                                    "description": "Delegate to an installed automation agent.",
                                },
                                {
                                    "const": "complete",
                                    "description": (
                                        "Terminate task with an explicit completion status."
                                    ),
                                },
                            ]
                        },
                        "reason": {
                            "type": "string",
                            "description": (
                                "One short sentence describing why this category is best now."
                            ),
                        },
                    },
                    "required": ["category", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sys__complete_task",
                "description": "Complete the task when done or failed",
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
                    "additionalProperties": False,
                },
            },
        },
    ]

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": _ROUTING_POLICY_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "observation": observation,
                        "task_state": task_state,
                        "todo_list": [todo_to_json(item) for item in todo_list],
                        "capabilities": capability_context,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "tools": route_tools,
        "tool_choice": "required",
    }

    try:
        response = chat_complete(exec_ctx, request)
        calls = parse_tool_calls(response)
        selection = pick_single_action_call(calls)
        if selection.call is None:
            return _fallback_category(capability_context)
        if selection.call.name == "sys__complete_task":
            set_pending_completion(exec_ctx, selection.call.arguments)
            return "complete"
        if selection.call.name == "sys__select_action_category":
            category = selection.call.arguments.get("category")
            if category in _ALLOWED_ROUTE_CATEGORIES:
                return str(category)
    except Exception:  # noqa: BLE001
        pass
    return _fallback_category(capability_context)


def _routing_capability_context(exec_ctx: PrivateAgentExecutionContext) -> JsonObject:
    query_names = sorted(item.name for item in data_queries.list_available(exec_ctx))
    boxy_tool_names = sorted(item.name for item in boxy_tools.list_available(exec_ctx))
    builtin_tool_names = sorted(item.name for item in builtin_tools.list_available(exec_ctx))
    automation_agents = sorted(
        item.name for item in exec_ctx.list_agents() if item.agent_type == "automation"
    )
    context: JsonObject = {
        "data_query": cast(
            JsonValue,
            {"count": len(query_names), "top_names": query_names[:5]},
        ),
        "boxy_tool": cast(
            JsonValue,
            {"count": len(boxy_tool_names), "top_names": boxy_tool_names[:5]},
        ),
        "builtin_tool": cast(
            JsonValue,
            {"count": len(builtin_tool_names), "top_names": builtin_tool_names[:5]},
        ),
        "delegate": cast(
            JsonValue,
            {"count": len(automation_agents), "top_names": automation_agents[:5]},
        ),
    }
    return context


def _fallback_category(capabilities: JsonObject) -> str:
    if _category_count(capabilities, "data_query") > 0:
        return "data_query"
    if _category_count(capabilities, "builtin_tool") > 0:
        return "builtin_tool"
    if _category_count(capabilities, "delegate") > 0:
        return "delegate"
    if _category_count(capabilities, "boxy_tool") > 0:
        return "boxy_tool"
    return "complete"


def _category_count(capabilities: JsonObject, category: str) -> int:
    raw = capabilities.get(category)
    if not isinstance(raw, dict):
        return 0
    count = raw.get("count")
    if not isinstance(count, int):
        return 0
    return max(count, 0)
