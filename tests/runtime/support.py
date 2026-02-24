from __future__ import annotations

from boxy_agent.models import AgentCapabilities, AgentType
from boxy_agent.public_sdk.interfaces import AgentMainFunction
from boxy_agent.runtime.discovery import DiscoveredAgent
from boxy_agent.runtime.models import InstalledAgent


def discovered_agent(
    *,
    name: str,
    handler: AgentMainFunction,
    agent_type: AgentType = "automation",
    expected_event_types: tuple[str, ...] = ("start",),
    capabilities: AgentCapabilities | None = None,
) -> DiscoveredAgent:
    return DiscoveredAgent(
        installed=InstalledAgent(
            name=name,
            description=f"{name} agent",
            version="1.0.0",
            agent_type=agent_type,
            expected_event_types=expected_event_types,
            capabilities=capabilities or AgentCapabilities(),
        ),
        handler=handler,
    )
