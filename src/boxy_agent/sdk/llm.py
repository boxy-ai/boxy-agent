"""Namespaced LLM helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.public_sdk.interfaces import AgentExecutionContext, runtime_bindings

__all__ = ["complete"]


def complete(exec_ctx: AgentExecutionContext, prompt: str, model: str | None = None) -> str:
    """Complete a prompt through the configured LLM provider."""
    return runtime_bindings(exec_ctx).llm_complete(prompt, model=model)
