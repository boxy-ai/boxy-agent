"""Action execution for the built-in main agent."""

from __future__ import annotations

import json
from typing import cast

from boxy_agent.models import AgentEvent
from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.sdk import boxy_tools, builtin_tools, data_queries, tracing
from boxy_agent.types import JsonValue

from .helpers import (
    JsonObject,
    chat_complete,
    idempotency_key,
    json_object,
    json_schema,
    parse_tool_calls,
    resolve_candidate_by_name,
    string_list,
)
from .orchestration import ToolCandidate, pick_single_action_call, to_openai_tool_name, top_k_tools


def execute_category_action(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    model: str,
    top_k: int,
    observation: JsonObject,
    task_state: JsonObject,
    category: str,
    recent_calls: dict[str, int],
) -> JsonObject:
    candidates = collect_candidates(exec_ctx)
    ranked = top_k_tools(
        query_text=json.dumps(observation, ensure_ascii=False),
        category=category,  # type: ignore[arg-type]
        tools=candidates,
        k=top_k,
        recent_calls=recent_calls,
    )
    tracing.trace(
        exec_ctx,
        "main.topk.selected",
        {
            "category": category,
            "candidate_count": len(candidates),
            "topk_count": len(ranked),
            "topk_names": [item.name for item in ranked],
        },
    )
    if not ranked:
        return {"ok": False, "error": "no_tools_for_category"}

    tool_map = {candidate.name: candidate for candidate in ranked}
    tools: list[JsonObject] = [candidate_to_openai_tool(candidate) for candidate in ranked]

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Use exactly one tool call."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "observation": observation,
                        "category": category,
                        "task_state": task_state,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "tools": cast(JsonValue, tools),
        "tool_choice": "required",
    }

    try:
        response = chat_complete(exec_ctx, cast(JsonObject, request))
        calls = parse_tool_calls(response)
        selection = pick_single_action_call(calls)
        if selection.call is None:
            tracing.trace(
                exec_ctx,
                "main.action.rejected",
                {"error": selection.error or "no_action"},
            )
            return {"ok": False, "error": selection.error or "no_action"}
        call = selection.call
        candidate = tool_map.get(call.name)
        if candidate is None:
            candidate = resolve_candidate_by_name(call.name, ranked)
        if candidate is None:
            return {
                "ok": False,
                "error": "unknown_tool",
                "requested_tool": call.name,
                "available_tools": [item.name for item in ranked],
            }
        return execute_candidate(exec_ctx, candidate, call.arguments)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def execute_delegate(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    model: str,
    observation: JsonObject,
    task_state: JsonObject,
) -> JsonObject:
    agents = [item for item in exec_ctx.list_agents() if item.agent_type == "automation"]
    if not agents:
        return {"ok": False, "error": "no_automation_agent"}

    agent_names = [item.name for item in agents]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "sys__delegate_to_automation",
                "description": "Delegate one objective to an automation agent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {"type": "string", "enum": agent_names},
                        "objective": {"type": "string"},
                        "context_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["agent_name", "objective"],
                },
            },
        }
    ]

    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Use delegation tool only."},
            {
                "role": "user",
                "content": json.dumps({"observation": observation, "task": task_state}),
            },
        ],
        "tools": cast(JsonValue, tools),
        "tool_choice": "required",
    }

    try:
        response = chat_complete(exec_ctx, cast(JsonObject, request))
        calls = parse_tool_calls(response)
        selection = pick_single_action_call(calls)
        if selection.call is None:
            return {"ok": False, "error": selection.error or "no_delegate_call"}
        call = selection.call
        if call.name != "sys__delegate_to_automation":
            return {"ok": False, "error": "invalid_delegate_tool"}
        agent_name = call.arguments.get("agent_name")
        objective = call.arguments.get("objective")
        context_refs_raw = call.arguments.get("context_refs")
        if not isinstance(agent_name, str) or not isinstance(objective, str):
            return {"ok": False, "error": "invalid_delegate_args"}
        context_refs = string_list(context_refs_raw)

        delegated = exec_ctx.delegate_to_agent(
            agent_name,
            AgentEvent(
                type="delegated.task",
                description=objective,
                payload={
                    "objective": objective,
                    "context_refs": cast(JsonValue, context_refs),
                },
            ),
        )
        return {
            "ok": True,
            "type": "delegate",
            "tool_name": "sys__delegate_to_automation",
            "data": {"delegated_output": delegated.output, "terminated": delegated.terminated},
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def collect_candidates(exec_ctx: PrivateAgentExecutionContext) -> list[ToolCandidate]:
    candidates: list[ToolCandidate] = []
    seen_names: set[str] = set()

    def register(candidate: ToolCandidate) -> None:
        base_name = candidate.name
        name = base_name
        if name in seen_names:
            # Resolve sanitized-name collisions deterministically and ensure final uniqueness.
            suffix = len(seen_names) + 1
            while True:
                maybe = f"{base_name[:56]}_{suffix}"
                if maybe not in seen_names:
                    name = maybe
                    break
                suffix += 1
        seen_names.add(name)
        candidates.append(
            ToolCandidate(
                name=name,
                capability_name=candidate.capability_name,
                category=candidate.category,
                description=candidate.description,
                input_schema=candidate.input_schema,
                side_effect=candidate.side_effect,
            )
        )

    for descriptor in data_queries.list_available(exec_ctx):
        register(
            ToolCandidate(
                name=to_openai_tool_name("dq", descriptor.name),
                capability_name=descriptor.name,
                category="data_query",
                description=descriptor.description,
                input_schema=json_schema(descriptor.input_schema),
            )
        )
    for descriptor in boxy_tools.list_available(exec_ctx):
        register(
            ToolCandidate(
                name=to_openai_tool_name("bt", descriptor.name),
                capability_name=descriptor.name,
                category="boxy_tool",
                description=descriptor.description,
                input_schema=json_schema(descriptor.input_schema),
                side_effect=True,
            )
        )
    for descriptor in builtin_tools.list_available(exec_ctx):
        register(
            ToolCandidate(
                name=to_openai_tool_name("bi", descriptor.name),
                capability_name=descriptor.name,
                category="builtin_tool",
                description=descriptor.description,
                input_schema=json_schema(descriptor.input_schema),
            )
        )
    return candidates


def candidate_to_openai_tool(candidate: ToolCandidate) -> JsonObject:
    return cast(
        JsonObject,
        {
            "type": "function",
            "function": {
                "name": candidate.name,
                "description": candidate.description,
                "parameters": (
                    candidate.input_schema
                    if isinstance(candidate.input_schema, dict)
                    else {"type": "object", "additionalProperties": True}
                ),
            },
        },
    )


def execute_candidate(
    exec_ctx: PrivateAgentExecutionContext,
    candidate: ToolCandidate,
    arguments: JsonObject,
) -> JsonObject:
    if candidate.category == "data_query":
        return {
            "ok": True,
            "type": candidate.category,
            "tool_name": candidate.name,
            "data": data_queries.query(
                exec_ctx,
                candidate.capability_name,
                json_object(arguments),
            ),
        }
    if candidate.category == "boxy_tool":
        params = json_object(arguments)
        if "idempotency_key" not in params:
            params["idempotency_key"] = idempotency_key(
                session_id=exec_ctx.session_id,
                tool_name=candidate.capability_name,
                params=params,
            )
        result = boxy_tools.call(exec_ctx, candidate.capability_name, params)
        return {
            "ok": True,
            "type": candidate.category,
            "tool_name": candidate.name,
            "data": result,
            "side_effect": candidate.side_effect,
        }
    if candidate.category == "builtin_tool":
        return {
            "ok": True,
            "type": candidate.category,
            "tool_name": candidate.name,
            "data": builtin_tools.call(
                exec_ctx,
                candidate.capability_name,
                json_object(arguments),
            ),
        }
    return {"ok": False, "error": "unsupported_category"}
