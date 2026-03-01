"""Namespaced control helper APIs for SDK consumers."""

from __future__ import annotations

from boxy_agent.sdk.interfaces import AgentExecutionContext, runtime_bindings

__all__ = ["terminate"]


def terminate(exec_ctx: AgentExecutionContext, reason: str | None = None) -> None:
    """Request session termination after the current step."""
    runtime_bindings(exec_ctx).terminate(reason)
