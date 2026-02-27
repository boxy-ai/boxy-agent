"""Private SDK interfaces built on top of the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from boxy_agent.models import AgentEvent
from boxy_agent.public_sdk.interfaces import (
    AgentExecutionContext,
    RuntimeBindings,
    runtime_bindings,
)
from boxy_agent.types import JsonValue

if TYPE_CHECKING:
    from boxy_agent.runtime.models import InstalledAgent


@dataclass(frozen=True)
class DelegateResult:
    """Result returned after delegating work to another installed agent."""

    output: JsonValue | None
    terminated: bool


class PrivateRuntimeBindings(RuntimeBindings, Protocol):
    """Runtime bindings required for private subagent orchestration."""

    def list_agents(self) -> list[InstalledAgent]:
        """List installed agents."""
        ...

    def delegate_to_agent(
        self,
        agent_name: str,
        event: AgentEvent,
    ) -> DelegateResult:
        """Delegate an event to another agent."""
        ...


@dataclass(kw_only=True)
class PrivateAgentExecutionContext(AgentExecutionContext):
    """Execution context with private-only discovery and delegation helpers."""

    def list_agents(self) -> list[InstalledAgent]:
        """List installed agents available for delegation."""
        return _private_runtime_bindings(self).list_agents()

    def delegate_to_agent(
        self,
        agent_name: str,
        event: AgentEvent,
    ) -> DelegateResult:
        """Delegate work to another installed agent."""
        return _private_runtime_bindings(self).delegate_to_agent(agent_name, event)


def _private_runtime_bindings(exec_ctx: AgentExecutionContext) -> PrivateRuntimeBindings:
    bindings = runtime_bindings(exec_ctx)
    if not hasattr(bindings, "list_agents") or not hasattr(bindings, "delegate_to_agent"):
        # Deferred import avoids private runtime dependency at module import time.
        from boxy_agent.runtime.errors import DelegationError

        raise DelegationError("This execution context does not support private delegation APIs")
    return cast(PrivateRuntimeBindings, bindings)
