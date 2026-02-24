"""Runtime domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from boxy_agent.models import AgentCapabilities, AgentEvent, AgentType
from boxy_agent.types import JsonValue

RunStatus = Literal[
    "idle",
    "terminated_by_agent",
    "terminated_by_controller",
]


@dataclass(frozen=True)
class InstalledAgent:
    """Discoverable installed agent descriptor."""

    name: str
    description: str
    version: str
    agent_type: AgentType
    expected_event_types: tuple[str, ...]
    capabilities: AgentCapabilities


@dataclass(frozen=True)
class TraceRecord:
    """Structured runtime trace record."""

    session_id: str
    agent_name: str
    event_type: str
    expected_event_types: tuple[str, ...]
    matched_expected_event_type: bool | None
    trace_name: str
    payload: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    """Summary of one agent run session."""

    session_id: str
    status: RunStatus
    last_output: JsonValue | None
    traces: list[TraceRecord]


@dataclass(frozen=True)
class EventQueueItem:
    """Event queue item produced by a connector or by an agent execution context."""

    event: AgentEvent
    source: str
    source_agent: str | None = None
    session_id: str | None = None
