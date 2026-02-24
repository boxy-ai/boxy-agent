"""Compiler and packaging result models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from boxy_agent.models import AgentCapabilities, AgentMetadata, AgentType
from boxy_agent.types import JsonValue

MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CompiledEntrypoint:
    """Canonical compiled entrypoint location."""

    module: str
    function: str


@dataclass(frozen=True)
class CompiledManifest:
    """Compiled manifest emitted by the compiler and embedded in wheels."""

    schema_version: int
    name: str
    description: str
    version: str
    agent_type: AgentType
    entrypoint: CompiledEntrypoint
    expected_event_types: tuple[str, ...]
    capabilities: AgentCapabilities

    @classmethod
    def from_metadata(
        cls,
        *,
        metadata: AgentMetadata,
        entrypoint_function: str,
    ) -> CompiledManifest:
        """Build a manifest from metadata and discovered entrypoint info."""
        return cls(
            schema_version=MANIFEST_SCHEMA_VERSION,
            name=metadata.name,
            description=metadata.description,
            version=metadata.version,
            agent_type=metadata.agent_type,
            entrypoint=CompiledEntrypoint(module=metadata.module, function=entrypoint_function),
            expected_event_types=metadata.expected_event_types,
            capabilities=metadata.capabilities,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize manifest to a JSON/TOML-compatible dictionary."""
        return cast(
            dict[str, JsonValue],
            {
                "schema_version": self.schema_version,
                "name": self.name,
                "description": self.description,
                "version": self.version,
                "type": self.agent_type,
                "entrypoint": {
                    "module": self.entrypoint.module,
                    "function": self.entrypoint.function,
                },
                "expected_event_types": list(self.expected_event_types),
                "capabilities": {
                    "data_queries": sorted(self.capabilities.data_queries),
                    "boxy_tools": sorted(self.capabilities.boxy_tools),
                    "builtin_tools": sorted(self.capabilities.builtin_tools),
                    "event_emitters": sorted(self.capabilities.event_emitters),
                },
            },
        )


@dataclass(frozen=True)
class CompiledAgent:
    """Result of ``compile_agent``."""

    project_dir: Path
    output_dir: Path
    module_path: Path
    manifest_path: Path
    manifest: CompiledManifest


@dataclass(frozen=True)
class PackagedAgent:
    """Result of ``package_agent``."""

    compiled: CompiledAgent
    wheel_path: Path
    manifest_module: str
