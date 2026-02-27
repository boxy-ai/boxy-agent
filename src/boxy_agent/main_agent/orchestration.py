"""Main-agent orchestration primitives for sparse planning and tool routing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from boxy_agent.types import JsonValue

ToolCategory = Literal["data_query", "boxy_tool", "builtin_tool", "delegate", "complete"]
TodoStatus = Literal["pending", "running", "done", "failed", "blocked"]
CompletionStatus = Literal[
    "success",
    "failed",
    "cancelled",
    "need_user_input",
    "waiting_external",
]

_OPENAI_TOOL_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_MAX_TOOL_NAME_LEN = 64
_DEFAULT_K = 12
_MAX_K = 20


@dataclass(frozen=True)
class ToolCandidate:
    name: str
    capability_name: str
    category: ToolCategory
    description: str
    input_schema: dict[str, JsonValue] | None = None
    side_effect: bool = False


@dataclass(frozen=True)
class ActionCall:
    name: str
    arguments: dict[str, JsonValue]


@dataclass(frozen=True)
class ActionSelection:
    call: ActionCall | None
    error: str | None = None


@dataclass(frozen=True)
class TodoItem:
    id: str
    title: str
    status: TodoStatus


@dataclass(frozen=True)
class CompletionGateInput:
    status: CompletionStatus
    evidence_refs: list[str]
    todo_list: list[TodoItem]
    side_effect_executed: bool
    known_evidence_refs: set[str] | None = None


@dataclass(frozen=True)
class CompletionGateDecision:
    accepted: bool
    reason: str | None = None


def should_replan(*, iteration: int, previous_step_failed: bool, todo_blocked: bool) -> bool:
    """Only replan on first iteration, after failures, or when work is blocked."""
    return iteration == 0 or previous_step_failed or todo_blocked


def to_openai_tool_name(prefix: str, capability_name: str) -> str:
    """Convert a capability id into OpenAI-compatible function name constraints."""
    normalized_prefix = _normalize_tool_segment(prefix)
    normalized_capability = _normalize_tool_segment(capability_name)
    base = (
        f"{normalized_prefix}__{normalized_capability}"
        if normalized_capability
        else normalized_prefix
    )

    if len(base) <= _MAX_TOOL_NAME_LEN:
        return base

    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    keep = _MAX_TOOL_NAME_LEN - len(normalized_prefix) - len(digest) - 4
    truncated = normalized_capability[: max(keep, 1)]
    return f"{normalized_prefix}__{truncated}_{digest}"


def top_k_tools(
    *,
    query_text: str,
    category: ToolCategory,
    tools: list[ToolCandidate],
    k: int = _DEFAULT_K,
    recent_calls: dict[str, int] | None = None,
) -> list[ToolCandidate]:
    """Filter by category and rank by lightweight heuristics before returning top-k."""
    bounded_k = min(max(k, 1), _MAX_K)
    recency = recent_calls or {}
    tokens = _tokenize(query_text)

    candidates = [tool for tool in tools if tool.category == category]
    scored = sorted(
        candidates,
        key=lambda tool: _score_tool(tool=tool, query_tokens=tokens, recency=recency),
        reverse=True,
    )
    return scored[:bounded_k]


def pick_single_action_call(calls: list[ActionCall]) -> ActionSelection:
    """Enforce one executable action tool call per iteration."""
    if not calls:
        return ActionSelection(call=None, error="no_tool_call")
    if len(calls) > 1:
        return ActionSelection(call=None, error="multiple_action_calls")
    return ActionSelection(call=calls[0], error=None)


def evaluate_completion_gate(input_data: CompletionGateInput) -> CompletionGateDecision:
    """Validate whether complete_task can terminate the loop."""
    if input_data.status != "success":
        return CompletionGateDecision(accepted=True, reason=None)

    has_pending = any(item.status not in {"done", "failed"} for item in input_data.todo_list)
    if has_pending:
        return CompletionGateDecision(accepted=False, reason="pending_todos")

    if input_data.side_effect_executed and not input_data.evidence_refs:
        return CompletionGateDecision(accepted=False, reason="missing_evidence")

    if input_data.evidence_refs and input_data.known_evidence_refs is not None:
        unknown = [
            ref for ref in input_data.evidence_refs if ref not in input_data.known_evidence_refs
        ]
        if unknown:
            return CompletionGateDecision(accepted=False, reason="unknown_evidence")

    return CompletionGateDecision(accepted=True, reason=None)


def _normalize_tool_segment(value: str) -> str:
    cleaned = _OPENAI_TOOL_NAME_PATTERN.sub("_", value.strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "tool"
    return cleaned


def _tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^a-zA-Z0-9]+", text.lower()) if token}


def _score_tool(
    *,
    tool: ToolCandidate,
    query_tokens: set[str],
    recency: dict[str, int],
) -> tuple[int, int, int, int, str]:
    searchable = f"{tool.name} {tool.capability_name} {tool.description}".lower()
    keyword_score = sum(1 for token in query_tokens if token in searchable)
    raw_recency = recency.get(tool.name, 0)
    recency_score = min(raw_recency, 2)
    repetition_penalty = -1 if raw_recency >= 4 else 0

    # Placeholder for optional embedding rerank integration.
    semantic_score = 0

    return keyword_score, semantic_score, recency_score, repetition_penalty, tool.name
