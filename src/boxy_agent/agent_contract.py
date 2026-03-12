"""Shared agent-type contract validation."""

from __future__ import annotations

from collections.abc import Callable

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import AgentCapabilities, AgentType


def validate_agent_type_contract(
    *,
    agent_type: AgentType,
    expected_event_types: tuple[str, ...],
    capabilities: AgentCapabilities,
    capability_catalog: CapabilityCatalog,
    raise_error: Callable[[str], Exception],
) -> None:
    """Validate agent-type rules that depend on declared capabilities."""
    if agent_type == "automation" and not expected_event_types:
        raise raise_error("Automation agents require non-empty expected_event_types")
    if agent_type == "data_mining" and expected_event_types:
        raise raise_error("Data mining agents must not declare expected_event_types")
    if agent_type != "data_mining":
        return

    unknown_boxy_tools = sorted(
        name for name in capabilities.boxy_tools if name not in capability_catalog.boxy_tools
    )
    if unknown_boxy_tools:
        rendered = ", ".join(unknown_boxy_tools)
        raise raise_error(f"Unknown boxy_tools: {rendered}")

    side_effecting_tools = sorted(
        name for name in capabilities.boxy_tools if capability_catalog.boxy_tools[name].side_effect
    )
    if side_effecting_tools:
        rendered = ", ".join(side_effecting_tools)
        raise raise_error(
            f"Data mining agents must not declare side-effecting boxy_tools: {rendered}"
        )
