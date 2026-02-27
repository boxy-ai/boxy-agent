"""Built-in Boxy main agent with observe-plan-act loop and layered tool discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from boxy_agent.models import AgentCapabilities, AgentResult
from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.sdk import boxy_tools, builtin_tools, control, data_queries, memory, tracing
from boxy_agent.types import JsonValue

from .completion_gate import call_complete_task
from .config import MainAgentConfig, load_main_agent_config
from .execution import (
    execute_category_action,
    execute_delegate,
)
from .helpers import (
    JsonObject,
    chat_complete,
    extract_evidence_refs,
    is_todo_status,
    json_object,
    known_evidence_refs,
    mark_next_todo,
    parse_tool_calls,
    recent_calls,
    todo_to_json,
)
from .orchestration import TodoItem, pick_single_action_call, should_replan
from .routing import route_action

ALLOWED_COMPLETION_STATUSES = {
    "success",
    "failed",
    "cancelled",
    "need_user_input",
    "waiting_external",
}
TASK_STATE_KEY = "main.task_state"
TODO_LIST_KEY = "main.todo_list"
LAST_OBSERVATION_KEY = "main.last_observation"
ITERATION_KEY = "main.iteration"
TERMINATION_KEY = "main.termination"
_CONFIG: MainAgentConfig = load_main_agent_config()


@dataclass(frozen=True)
class _LoopState:
    iteration: int
    task_state: JsonObject
    todo_list: list[TodoItem]
    last_observation: JsonObject


def handle(exec_ctx: PrivateAgentExecutionContext) -> AgentResult:
    state = _load_state(exec_ctx)
    observation = _initial_observation(exec_ctx, state.last_observation)
    tracing.trace(exec_ctx, "main.loop.start", {"iteration": state.iteration})

    for _ in range(_CONFIG.max_iterations):
        todo_blocked = _todo_blocked(state.todo_list)
        previous_failed = bool(state.task_state.get("previous_step_failed", False))

        if should_replan(
            iteration=state.iteration,
            previous_step_failed=previous_failed,
            todo_blocked=todo_blocked,
        ):
            state = _maybe_replan(exec_ctx, state=state, observation=observation)

        route = _route_action(exec_ctx, state=state, observation=observation)
        tracing.trace(
            exec_ctx,
            "main.route.selected",
            {"route": route, "iteration": state.iteration},
        )
        if route == "complete":
            completion = _call_complete_task(exec_ctx, state=state, observation=observation)
            if completion is not None:
                return completion
            state = _next_state_after_completion_rejected(
                exec_ctx,
                state,
                observation=observation,
            )
            observation = state.last_observation
            continue

        if route == "delegate":
            delegate_observation = _execute_delegate(exec_ctx, state=state, observation=observation)
            if delegate_observation.get("ok") is True:
                state = _next_state_after_success(exec_ctx, state, delegate_observation)
            else:
                state = _next_state_after_error(
                    exec_ctx,
                    state,
                    error=str(delegate_observation.get("error", "delegate_failed")),
                    observation=delegate_observation,
                )
            observation = state.last_observation
            continue

        action_observation = _execute_category_action(
            exec_ctx,
            state=state,
            observation=observation,
            category=route,
        )
        if action_observation.get("ok") is True:
            state = _next_state_after_success(exec_ctx, state, action_observation)
            completion = _call_complete_task(
                exec_ctx,
                state=state,
                observation=state.last_observation,
            )
            if completion is not None:
                return completion
        else:
            state = _next_state_after_error(
                exec_ctx,
                state,
                error=str(action_observation.get("error", "action_failed")),
                observation=action_observation,
            )
        observation = state.last_observation

    termination = {
        "status": "failed",
        "reason": "iteration_limit_exceeded",
        "iteration": state.iteration,
    }
    memory.set(exec_ctx, TERMINATION_KEY, termination)
    control.terminate(exec_ctx, "iteration_limit_exceeded")
    return AgentResult(output=termination)


def build_main_agent_capabilities(exec_ctx: PrivateAgentExecutionContext) -> AgentCapabilities:
    return AgentCapabilities(
        data_queries=frozenset(item.name for item in data_queries.list_available(exec_ctx)),
        boxy_tools=frozenset(item.name for item in boxy_tools.list_available(exec_ctx)),
        builtin_tools=frozenset(item.name for item in builtin_tools.list_available(exec_ctx)),
        event_emitters=frozenset(),
    )


def _load_state(exec_ctx: PrivateAgentExecutionContext) -> _LoopState:
    raw_iteration = memory.get(exec_ctx, ITERATION_KEY)
    iteration = raw_iteration if isinstance(raw_iteration, int) and raw_iteration >= 0 else 0

    raw_task_state = memory.get(exec_ctx, TASK_STATE_KEY)
    task_state = json_object(raw_task_state)

    raw_last_observation = memory.get(exec_ctx, LAST_OBSERVATION_KEY)
    last_observation = json_object(raw_last_observation)
    if not last_observation:
        last_observation = {
            "type": "none",
            "payload": {},
        }

    raw_todo = memory.get(exec_ctx, TODO_LIST_KEY)
    todo_list: list[TodoItem] = []
    if isinstance(raw_todo, list):
        for item in raw_todo:
            if not isinstance(item, dict):
                continue
            todo_id = item.get("id")
            title = item.get("title")
            status = item.get("status")
            if isinstance(todo_id, str) and isinstance(title, str) and is_todo_status(status):
                todo_list.append(TodoItem(id=todo_id, title=title, status=status))

    return _LoopState(
        iteration=iteration,
        task_state=task_state,
        todo_list=todo_list,
        last_observation=last_observation,
    )


def _initial_observation(
    exec_ctx: PrivateAgentExecutionContext,
    last_observation: JsonObject,
) -> JsonObject:
    if last_observation.get("type") == "none":
        return {
            "type": "event",
            "event": {
                "type": exec_ctx.event.type,
                "description": exec_ctx.event.description,
                "payload": exec_ctx.event.payload,
            },
        }
    return last_observation


def _maybe_replan(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    state: _LoopState,
    observation: JsonObject,
) -> _LoopState:
    replan_tool = {
        "type": "function",
        "function": {
            "name": "sys__patch_plan",
            "description": (
                "Patch planning state conservatively. Keep unchanged fields absent to preserve "
                "existing plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_state": {"type": "object", "additionalProperties": True},
                    "todo_list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "running", "done", "failed", "blocked"],
                                },
                            },
                            "required": ["title"],
                            "additionalProperties": True,
                        },
                    },
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    }
    request = {
        "model": _CONFIG.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Use sys__patch_plan only. Keep plans stable. Patch only what changed."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "observation": observation,
                        "task_state": state.task_state,
                        "todo_list": [todo_to_json(item) for item in state.todo_list],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "tools": [replan_tool],
        "tool_choice": "required",
    }
    try:
        response = chat_complete(exec_ctx, request)
        calls = parse_tool_calls(response)
        selection = pick_single_action_call(calls)
        if selection.call is None or selection.call.name != "sys__patch_plan":
            return state
        patch = selection.call.arguments
    except Exception:  # noqa: BLE001
        return state

    if not isinstance(patch, dict):
        return state

    next_task_state = dict(state.task_state)
    patch_task_state = patch.get("task_state")
    if isinstance(patch_task_state, dict):
        next_task_state.update(json_object(patch_task_state))

    next_todo = state.todo_list
    patch_todo = patch.get("todo_list")
    if isinstance(patch_todo, list):
        if len(patch_todo) == 0:
            next_todo = []

        parsed: list[TodoItem] = []
        for idx, item in enumerate(patch_todo):
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            status = item.get("status", "pending")
            if isinstance(title, str) and is_todo_status(status):
                parsed.append(
                    TodoItem(
                        id=str(item.get("id", f"plan-{idx + 1}")),
                        title=title,
                        status=status,
                    )
                )
        if parsed:
            next_todo = parsed

    return _LoopState(
        iteration=state.iteration,
        task_state=next_task_state,
        todo_list=next_todo,
        last_observation=state.last_observation,
    )


def _route_action(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    state: _LoopState,
    observation: JsonObject,
) -> str:
    return route_action(
        exec_ctx,
        model=_CONFIG.model,
        observation=observation,
        task_state=state.task_state,
        todo_list=state.todo_list,
    )


def _execute_category_action(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    state: _LoopState,
    observation: JsonObject,
    category: str,
) -> JsonObject:
    return execute_category_action(
        exec_ctx,
        model=_CONFIG.model,
        top_k=_CONFIG.top_k,
        observation=observation,
        task_state=state.task_state,
        category=category,
        recent_calls=recent_calls(state.task_state),
    )


def _execute_delegate(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    state: _LoopState,
    observation: JsonObject,
) -> JsonObject:
    return execute_delegate(
        exec_ctx,
        model=_CONFIG.model,
        observation=observation,
        task_state=state.task_state,
    )


def _call_complete_task(
    exec_ctx: PrivateAgentExecutionContext,
    *,
    state: _LoopState,
    observation: JsonObject,
) -> AgentResult | None:
    return call_complete_task(
        exec_ctx,
        model=_CONFIG.model,
        termination_key=TERMINATION_KEY,
        allowed_statuses=ALLOWED_COMPLETION_STATUSES,
        task_state=state.task_state,
        todo_list=state.todo_list,
        observation=observation,
        todo_list_json=[todo_to_json(item) for item in state.todo_list],
    )


def _next_state_after_success(
    exec_ctx: PrivateAgentExecutionContext,
    state: _LoopState,
    observation: JsonObject,
) -> _LoopState:
    next_iteration = state.iteration + 1
    next_task_state = dict(state.task_state)
    next_task_state["previous_step_failed"] = False
    next_todo = mark_next_todo(state.todo_list, status="done")
    recent = recent_calls(next_task_state)
    call_name = str(observation.get("tool_name", observation.get("type", "unknown")))
    recent[call_name] = recent.get(call_name, 0) + 1
    next_task_state["recent_calls"] = cast(
        JsonValue,
        {key: value for key, value in recent.items()},
    )
    if observation.get("side_effect") is True:
        next_task_state["side_effect_executed"] = True
    extracted = extract_evidence_refs(observation)
    if extracted:
        known = known_evidence_refs(next_task_state)
        known.update(extracted)
        next_task_state["known_evidence_refs"] = cast(JsonValue, sorted(known))

    memory.set(exec_ctx, ITERATION_KEY, next_iteration)
    memory.set(exec_ctx, TASK_STATE_KEY, next_task_state)
    memory.set(exec_ctx, LAST_OBSERVATION_KEY, observation)
    memory.set(exec_ctx, TODO_LIST_KEY, [todo_to_json(item) for item in next_todo])
    return _LoopState(
        iteration=next_iteration,
        task_state=next_task_state,
        todo_list=next_todo,
        last_observation=observation,
    )


def _next_state_after_error(
    exec_ctx: PrivateAgentExecutionContext,
    state: _LoopState,
    *,
    error: str,
    observation: JsonObject,
) -> _LoopState:
    next_iteration = state.iteration + 1
    next_task_state = dict(state.task_state)
    next_task_state["previous_step_failed"] = True
    next_todo = mark_next_todo(state.todo_list, status="failed")
    next_observation: JsonObject = {
        "ok": False,
        "type": "error",
        "error": error,
        "last": observation,
    }

    memory.set(exec_ctx, ITERATION_KEY, next_iteration)
    memory.set(exec_ctx, TASK_STATE_KEY, next_task_state)
    memory.set(exec_ctx, LAST_OBSERVATION_KEY, next_observation)
    memory.set(exec_ctx, TODO_LIST_KEY, [todo_to_json(item) for item in next_todo])
    return _LoopState(
        iteration=next_iteration,
        task_state=next_task_state,
        todo_list=next_todo,
        last_observation=next_observation,
    )


def _next_state_after_completion_rejected(
    exec_ctx: PrivateAgentExecutionContext,
    state: _LoopState,
    *,
    observation: JsonObject,
) -> _LoopState:
    next_iteration = state.iteration + 1
    next_task_state = dict(state.task_state)
    # Completion rejection should not force plan regeneration next iteration.
    next_task_state["previous_step_failed"] = False
    next_observation: JsonObject = {
        "ok": False,
        "type": "completion_rejected",
        "error": "completion_rejected",
        "last": observation,
    }

    memory.set(exec_ctx, ITERATION_KEY, next_iteration)
    memory.set(exec_ctx, TASK_STATE_KEY, next_task_state)
    memory.set(exec_ctx, LAST_OBSERVATION_KEY, next_observation)
    memory.set(exec_ctx, TODO_LIST_KEY, [todo_to_json(item) for item in state.todo_list])
    return _LoopState(
        iteration=next_iteration,
        task_state=next_task_state,
        todo_list=state.todo_list,
        last_observation=next_observation,
    )


def _todo_blocked(todo_list: list[TodoItem]) -> bool:
    # Empty todo list is allowed after successful direct actions; do not force replan loop.
    if not todo_list:
        return False
    return all(item.status in {"done", "failed", "blocked"} for item in todo_list)
