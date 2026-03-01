"""Namespaced LLM helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.sdk.interfaces import AgentExecutionContext, runtime_bindings
from boxy_agent.types import JsonValue

__all__ = ["chat_complete"]


def chat_complete(
    exec_ctx: AgentExecutionContext,
    request: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Complete a chat request through the configured LLM provider."""
    return runtime_bindings(exec_ctx).llm_chat_complete(request)
