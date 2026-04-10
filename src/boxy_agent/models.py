"""Data models for the Boxy agent SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from boxy_agent.types import JsonValue, ensure_json_value

AgentType = Literal["automation", "data_mining"]
ResultContract = Literal[
    "raw",
    "read_result",
    "mutation_result",
]


@dataclass(frozen=True)
class DataQueryDescriptor:
    """Describes a discoverable Boxy data query."""

    name: str
    description: str
    output_schema: dict[str, JsonValue]
    input_schema: dict[str, JsonValue] = field(
        default_factory=lambda: {
            "type": "object",
            "additionalProperties": True,
        }
    )
    result_contract: ResultContract = "raw"
    max_limit: int | None = None

    def __post_init__(self) -> None:
        _require_non_empty("name", self.name)
        _require_non_empty("description", self.description)
        for key, value in self.input_schema.items():
            _require_non_empty("input schema key", key)
            ensure_json_value(value, label=f"input schema value for {self.name}:{key}")
        for key, value in self.output_schema.items():
            _require_non_empty("output schema key", key)
            ensure_json_value(value, label=f"output schema value for {self.name}:{key}")
        _require_result_contract(self.result_contract, label=f"result contract for {self.name}")
        if self.max_limit is not None and self.max_limit < 1:
            raise ValueError("max_limit must be >= 1 when provided")


@dataclass(frozen=True)
class ToolDescriptor:
    """Describes a discoverable tool interface."""

    name: str
    description: str
    input_schema: dict[str, JsonValue] = field(
        default_factory=lambda: {
            "type": "object",
            "additionalProperties": True,
        }
    )
    output_schema: dict[str, JsonValue] = field(default_factory=dict)
    result_contract: ResultContract = "raw"
    side_effect: bool = False

    def __post_init__(self) -> None:
        _require_non_empty("name", self.name)
        _require_non_empty("description", self.description)
        if not isinstance(self.side_effect, bool):
            raise TypeError("side_effect must be a boolean")
        for key, value in self.input_schema.items():
            _require_non_empty("input schema key", key)
            ensure_json_value(value, label=f"input schema value for {self.name}:{key}")
        for key, value in self.output_schema.items():
            _require_non_empty("output schema key", key)
            ensure_json_value(value, label=f"output schema value for {self.name}:{key}")
        _require_result_contract(self.result_contract, label=f"result contract for {self.name}")


@dataclass(frozen=True)
class AgentCapabilities:
    """Capability declarations for agent data and tool access."""

    data_queries: frozenset[str] = field(default_factory=frozenset)
    boxy_tools: frozenset[str] = field(default_factory=frozenset)
    builtin_tools: frozenset[str] = field(default_factory=frozenset)
    event_emitters: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "data_queries", _normalize_name_set(self.data_queries, "data_queries")
        )
        object.__setattr__(self, "boxy_tools", _normalize_name_set(self.boxy_tools, "boxy_tools"))
        object.__setattr__(
            self,
            "builtin_tools",
            _normalize_name_set(self.builtin_tools, "builtin_tools"),
        )
        object.__setattr__(
            self,
            "event_emitters",
            _normalize_name_set(self.event_emitters, "event_emitters"),
        )


@dataclass(frozen=True)
class AgentMetadata:
    """Metadata loaded from ``pyproject.toml`` and carried into compiled manifests."""

    name: str
    description: str
    version: str
    agent_type: AgentType
    module: str
    expected_event_types: tuple[str, ...]
    capabilities: AgentCapabilities

    def __post_init__(self) -> None:
        _require_non_empty("name", self.name)
        _require_non_empty("description", self.description)
        _require_non_empty("version", self.version)
        _require_non_empty("module", self.module)
        if self.agent_type not in {"automation", "data_mining"}:
            raise ValueError(f"Unsupported agent_type: {self.agent_type}")
        normalized = tuple(
            _normalize_name(event_type, "expected_event_types")
            for event_type in self.expected_event_types
        )
        object.__setattr__(self, "expected_event_types", normalized)


@dataclass(frozen=True)
class AgentEvent:
    """Event record for runtime events passed to agent entrypoints."""

    type: str
    description: str = ""
    payload: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty("type", self.type)
        if not isinstance(self.description, str):
            raise TypeError("description must be a string")
        for key, value in self.payload.items():
            _require_non_empty("payload key", key)
            ensure_json_value(value, label=f"event payload value for key {key}")


@dataclass(frozen=True)
class AgentResult:
    """Result produced by an agent step."""

    output: JsonValue | None = None
    session_memory_updates: dict[str, JsonValue] = field(default_factory=dict)
    persistent_memory_updates: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_json_value(self.output, label="output")
        for key, value in self.session_memory_updates.items():
            _require_non_empty("session memory key", key)
            ensure_json_value(value, label=f"session memory value for key {key}")
        for key, value in self.persistent_memory_updates.items():
            _require_non_empty("persistent memory key", key)
            ensure_json_value(value, label=f"persistent memory value for key {key}")


def _normalize_name_set(values: frozenset[str], label: str) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        normalized.add(_normalize_name(value, label))
    return frozenset(normalized)


def _normalize_name(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} entries must be strings")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{label} entries must be non-empty")
    return stripped


def _require_non_empty(label: str, value: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")


def _require_result_contract(value: str, *, label: str) -> None:
    if value not in {
        "raw",
        "read_result",
        "mutation_result",
    }:
        raise ValueError(f"Unsupported {label}: {value}")


def parse_agent_type(value: str) -> AgentType:
    """Parse and validate an agent type literal."""
    if value not in {"automation", "data_mining"}:
        raise ValueError(f"Unsupported agent type: {value}")
    return cast(AgentType, value)
