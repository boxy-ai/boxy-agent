"""Shared helper functions for the built-in main agent."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TypeGuard

from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.public_sdk.interfaces import runtime_bindings
from boxy_agent.sdk import llm, memory
from boxy_agent.types import JsonValue, is_json_value

from .orchestration import ActionCall, TodoItem, TodoStatus, ToolCandidate

_ALLOWED_TODO_STATUSES = {"pending", "running", "done", "failed", "blocked"}
_DEDUPE_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+)_(?P<suffix>[0-9]+)$")

type JsonObject = dict[str, JsonValue]


def assistant_content(response: JsonObject) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def parse_tool_calls(response: JsonObject) -> list[ActionCall]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    choice = choices[0]
    if not isinstance(choice, dict):
        return []
    message = choice.get("message")
    if not isinstance(message, dict):
        return []

    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []

    calls: list[ActionCall] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        arguments_text = function.get("arguments", "{}")
        if not isinstance(name, str):
            continue
        if isinstance(arguments_text, str):
            try:
                arguments = json.loads(arguments_text)
            except json.JSONDecodeError:
                arguments = {}
        elif isinstance(arguments_text, dict):
            arguments = dict(arguments_text)
        else:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ActionCall(name=name, arguments=json_object(arguments)))
    return calls


def json_object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    normalized: JsonObject = {}
    for key, val in value.items():
        if isinstance(key, str) and is_json_value(val):
            normalized[key] = val
    return normalized


def recent_calls(task_state: JsonObject) -> dict[str, int]:
    raw = task_state.get("recent_calls")
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, int) and value >= 0:
            parsed[key] = value
    return parsed


def known_evidence_refs(task_state: JsonObject) -> set[str]:
    raw = task_state.get("known_evidence_refs")
    if not isinstance(raw, list):
        return set()
    parsed: set[str] = set()
    for item in raw:
        if isinstance(item, str) and item:
            parsed.add(item)
    return parsed


def todo_to_json(item: TodoItem) -> JsonObject:
    return {"id": item.id, "title": item.title, "status": item.status}


def is_todo_status(value: object) -> TypeGuard[TodoStatus]:
    return isinstance(value, str) and value in _ALLOWED_TODO_STATUSES


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def mark_next_todo(todo_list: list[TodoItem], *, status: TodoStatus) -> list[TodoItem]:
    updated: list[TodoItem] = []
    changed = False
    for item in todo_list:
        if not changed and item.status in {"pending", "running", "blocked"}:
            updated.append(TodoItem(id=item.id, title=item.title, status=status))
            changed = True
        else:
            updated.append(item)
    return updated


def json_schema(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {"type": "object", "additionalProperties": True}
    return {str(key): val for key, val in value.items() if is_json_value(val)}


def resolve_candidate_by_name(name: str, ranked: list[ToolCandidate]) -> ToolCandidate | None:
    normalized = name.strip()
    if not normalized:
        return None
    for item in ranked:
        if item.name == normalized:
            return item

    # Only accept explicit tool names that were actually offered.
    # Unknown suffixed names (for example "..._99") must not fallback to base tools.
    if split_dedupe_suffix(normalized) is not None:
        return None

    suffixed_matches = [
        item
        for item in ranked
        if (split := split_dedupe_suffix(item.name)) is not None and split[0] == normalized
    ]
    if len(suffixed_matches) == 1:
        return suffixed_matches[0]
    return None


def split_dedupe_suffix(value: str) -> tuple[str, int] | None:
    match = _DEDUPE_SUFFIX_PATTERN.fullmatch(value)
    if match is None:
        return None
    base = match.group("base")
    suffix_text = match.group("suffix")
    try:
        suffix = int(suffix_text)
    except ValueError:
        return None
    if suffix <= 0:
        return None
    return base, suffix


def idempotency_key(
    *,
    session_id: str,
    tool_name: str,
    params: JsonObject,
) -> str:
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(f"{session_id}|{tool_name}|{payload}".encode()).hexdigest()[:16]
    return f"main-{digest}"


def extract_evidence_refs(observation: JsonObject) -> set[str]:
    refs: set[str] = set()
    _collect_evidence_refs(observation, refs, depth=0)
    return refs


def _collect_evidence_refs(value: object, refs: set[str], *, depth: int) -> None:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "evidence_refs" and isinstance(nested, list):
                for item in nested:
                    if isinstance(item, str) and item:
                        refs.add(item)
                continue
            _collect_evidence_refs(nested, refs, depth=depth + 1)
        return
    if isinstance(value, list):
        for nested in value:
            _collect_evidence_refs(nested, refs, depth=depth + 1)


def chat_complete(exec_ctx: PrivateAgentExecutionContext, request: JsonObject) -> JsonObject:
    chat_complete_fn = getattr(llm, "chat_complete", None)
    if callable(chat_complete_fn):
        response = chat_complete_fn(exec_ctx, request)  # type: ignore[arg-type]
        if isinstance(response, dict):
            return json_object(response)
        raise TypeError("llm.chat_complete must return a JSON object")

    bindings = runtime_bindings(exec_ctx)
    bindings_chat_complete = getattr(bindings, "llm_chat_complete", None)
    if callable(bindings_chat_complete):
        response = bindings_chat_complete(request)  # type: ignore[misc]
        if isinstance(response, dict):
            return json_object(response)
        raise TypeError("runtime llm_chat_complete must return a JSON object")

    raise RuntimeError("No chat-completion interface available in current boxy-agent runtime")


def set_pending_completion(exec_ctx: PrivateAgentExecutionContext, payload: JsonObject) -> None:
    memory.set(exec_ctx, "main.pending_completion", payload)


def pop_pending_completion(exec_ctx: PrivateAgentExecutionContext) -> JsonObject | None:
    raw = memory.get(exec_ctx, "main.pending_completion")
    memory.delete(exec_ctx, "main.pending_completion")
    if isinstance(raw, dict):
        return json_object(raw)
    return None
