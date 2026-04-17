"""Metadata loading and validation from ``pyproject.toml``."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from boxy_agent._version import __version__ as BOXY_AGENT_VERSION
from boxy_agent.agent_contract import validate_agent_type_contract
from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.compatibility import (
    CompatibilityError,
    extract_boxy_agent_requirement,
    require_boxy_agent_requirement_satisfied,
)
from boxy_agent.models import AgentCapabilities, AgentMetadata, parse_agent_type

METADATA_FILE_NAME = "pyproject.toml"


class MetadataValidationError(ValueError):
    """Raised when Boxy metadata in ``pyproject.toml`` is missing or invalid."""


def load_agent_metadata(
    project_dir: Path,
    *,
    capability_catalog: CapabilityCatalog,
) -> AgentMetadata:
    """Load and validate metadata from ``pyproject.toml``."""
    if capability_catalog is None:
        raise MetadataValidationError("capability_catalog is required")
    catalog = capability_catalog

    metadata_path = project_dir / METADATA_FILE_NAME
    if not metadata_path.exists():
        raise MetadataValidationError(f"Missing metadata file: {metadata_path}")

    data = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MetadataValidationError("Metadata file must contain a TOML table")

    project_table = _require_table(data, "project")
    dependencies = _optional_string_list(project_table, "dependencies")
    try:
        boxy_agent_requirement = extract_boxy_agent_requirement(
            dependencies=dependencies,
            source=f"{metadata_path} [project].dependencies",
        )
        require_boxy_agent_requirement_satisfied(
            specifier=boxy_agent_requirement,
            sdk_version=BOXY_AGENT_VERSION,
            source=f"{metadata_path} [project].dependencies",
        )
    except CompatibilityError as exc:
        raise MetadataValidationError(str(exc)) from exc

    tool_table = _require_table(data, "tool")
    boxy_table = _require_table(tool_table, "boxy_agent")
    agent_table = _require_table(boxy_table, "agent")
    capabilities_table = _require_table(boxy_table, "capabilities")

    name = _require_string(agent_table, "name")
    description = _require_string(agent_table, "description")
    version = _require_string(agent_table, "version")
    try:
        agent_type = parse_agent_type(_require_string(agent_table, "type"))
    except ValueError as exc:
        raise MetadataValidationError(str(exc)) from exc
    module = _require_string(agent_table, "module")
    _validate_module(module)
    expected_event_types = tuple(_optional_string_list(agent_table, "expected_event_types"))

    data_queries = frozenset(_optional_string_list(capabilities_table, "data_queries"))
    boxy_tools = frozenset(_optional_string_list(capabilities_table, "boxy_tools"))
    builtin_tools = frozenset(_optional_string_list(capabilities_table, "builtin_tools"))
    event_emitters = frozenset(_optional_string_list(capabilities_table, "event_emitters"))

    _validate_capabilities(
        data_queries,
        known=catalog.known_data_queries(),
        label="data_queries",
    )
    _validate_capabilities(
        boxy_tools,
        known=catalog.known_boxy_tools(),
        label="boxy_tools",
    )
    _validate_capabilities(
        builtin_tools,
        known=catalog.known_builtin_tools(),
        label="builtin_tools",
    )

    capabilities = AgentCapabilities(
        data_queries=data_queries,
        boxy_tools=boxy_tools,
        builtin_tools=builtin_tools,
        event_emitters=event_emitters,
    )
    validate_agent_type_contract(
        agent_type=agent_type,
        expected_event_types=expected_event_types,
        capabilities=capabilities,
        capability_catalog=catalog,
        raise_error=MetadataValidationError,
    )

    return AgentMetadata(
        name=name,
        description=description,
        version=version,
        boxy_agent_requirement=boxy_agent_requirement,
        agent_type=agent_type,
        module=module,
        expected_event_types=expected_event_types,
        capabilities=capabilities,
    )


def _require_table(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise MetadataValidationError(f"Missing required TOML table: {key}")
    return cast(dict[str, object], value)


def _require_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise MetadataValidationError(f"{key} must be a string")
    normalized = value.strip()
    if not normalized:
        raise MetadataValidationError(f"{key} must be non-empty")
    return normalized


def _optional_string_list(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise MetadataValidationError(f"{key} must be a list of strings")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise MetadataValidationError(f"{key} must contain only strings")
        stripped = item.strip()
        if not stripped:
            raise MetadataValidationError(f"{key} entries must be non-empty")
        normalized.append(stripped)
    return normalized


def _validate_capabilities(
    declared: frozenset[str],
    *,
    known: frozenset[str],
    label: str,
) -> None:
    unknown = sorted(declared - known)
    if unknown:
        raise MetadataValidationError(f"Unknown {label}: {', '.join(unknown)}")


def _validate_module(module: str) -> None:
    parts = module.split(".")
    if len(parts) < 2:
        raise MetadataValidationError(
            "module must be a dotted import path like '<package>.<module>'"
        )
    for part in parts:
        if not part.isidentifier():
            raise MetadataValidationError(
                "module must contain only valid python identifier segments separated by '.'"
            )
