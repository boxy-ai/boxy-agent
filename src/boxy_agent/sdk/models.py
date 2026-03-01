"""Namespaced model and context types for SDK consumers."""

from __future__ import annotations

from boxy_agent.models import (
    AgentCapabilities,
    AgentEvent,
    AgentMetadata,
    AgentResult,
    DataQueryDescriptor,
    ToolDescriptor,
)
from boxy_agent.sdk.interfaces import AgentExecutionContext
from boxy_agent.types import JsonValue

__all__ = [
    "AgentCapabilities",
    "AgentExecutionContext",
    "AgentEvent",
    "AgentMetadata",
    "AgentResult",
    "DataQueryDescriptor",
    "JsonValue",
    "ToolDescriptor",
]
