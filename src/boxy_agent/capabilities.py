"""Capability catalog loading and validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from boxy_agent.models import DataQueryDescriptor, ToolDescriptor
from boxy_agent.types import JsonValue, ensure_json_value

CATALOG_SCHEMA_VERSION = 1


class CapabilityCatalogError(ValueError):
    """Raised when a capability catalog cannot be loaded or validated."""


@dataclass(frozen=True)
class CapabilityCatalog:
    """Discoverable capabilities and schemas available to compile/runtime."""

    data_queries: dict[str, DataQueryDescriptor]
    boxy_tools: dict[str, ToolDescriptor]
    builtin_tools: dict[str, ToolDescriptor]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data_queries",
            _normalized_data_query_registry(self.data_queries, label="data_queries"),
        )
        object.__setattr__(
            self,
            "boxy_tools",
            _normalized_tool_registry(self.boxy_tools, label="boxy_tools"),
        )
        object.__setattr__(
            self,
            "builtin_tools",
            _normalized_tool_registry(self.builtin_tools, label="builtin_tools"),
        )

    def known_data_queries(self) -> frozenset[str]:
        """Return all known data query names."""
        return frozenset(self.data_queries)

    def known_boxy_tools(self) -> frozenset[str]:
        """Return all known Boxy tool names."""
        return frozenset(self.boxy_tools)

    def known_builtin_tools(self) -> frozenset[str]:
        """Return all known built-in tool names."""
        return frozenset(self.builtin_tools)


def load_capability_catalog(path: Path) -> CapabilityCatalog:
    """Load and validate a capability catalog from a TOML file."""
    resolved = path.resolve()
    if not resolved.exists():
        raise CapabilityCatalogError(f"Missing capability catalog file: {resolved}")
    payload = resolved.read_text(encoding="utf-8")
    return load_capability_catalog_from_text(payload, source=str(resolved))


def load_capability_catalog_from_text(text: str, *, source: str = "<memory>") -> CapabilityCatalog:
    """Load and validate a capability catalog from TOML text."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CapabilityCatalogError(f"Invalid capability catalog TOML ({source}): {exc}") from exc

    if not isinstance(raw, dict):
        raise CapabilityCatalogError(f"Capability catalog must be a TOML table ({source})")

    schema_version = raw.get("schema_version", CATALOG_SCHEMA_VERSION)
    if not isinstance(schema_version, int):
        raise CapabilityCatalogError("Capability catalog schema_version must be an integer")
    if schema_version != CATALOG_SCHEMA_VERSION:
        raise CapabilityCatalogError(
            "Unsupported capability catalog schema_version "
            f"{schema_version}; expected {CATALOG_SCHEMA_VERSION}"
        )

    data_queries = _load_data_queries(raw.get("data_queries"), source=source)
    boxy_tools = _load_tools(raw.get("boxy_tools"), source=source, label="boxy_tools")
    builtin_tools = _load_tools(raw.get("builtin_tools"), source=source, label="builtin_tools")

    return CapabilityCatalog(
        data_queries=data_queries,
        boxy_tools=boxy_tools,
        builtin_tools=builtin_tools,
    )


def _load_data_queries(value: object, *, source: str) -> dict[str, DataQueryDescriptor]:
    entries = _require_list(value, "data_queries", source=source)
    by_name: dict[str, DataQueryDescriptor] = {}
    for index, entry in enumerate(entries):
        table = _require_table(entry, f"data_queries[{index}]", source=source)
        name = _require_string(table, "name", label=f"data_queries[{index}]")
        if name in by_name:
            raise CapabilityCatalogError(f"Duplicate data query capability '{name}' ({source})")
        description = _require_string(table, "description", label=f"data_queries[{index}]")
        input_schema = _require_schema(
            table,
            "input_schema",
            capability_name=name,
            source=source,
        )
        output_schema = _require_schema(
            table,
            "output_schema",
            capability_name=name,
            source=source,
        )
        query_capabilities = _optional_json_table(
            table,
            "query_capabilities",
            label=f"data_queries[{index}]",
            source=source,
        )
        by_name[name] = DataQueryDescriptor(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            query_capabilities=query_capabilities,
        )
    return by_name


def _load_tools(value: object, *, source: str, label: str) -> dict[str, ToolDescriptor]:
    entries = _require_list(value, label, source=source)
    by_name: dict[str, ToolDescriptor] = {}
    for index, entry in enumerate(entries):
        table = _require_table(entry, f"{label}[{index}]", source=source)
        name = _require_string(table, "name", label=f"{label}[{index}]")
        if name in by_name:
            raise CapabilityCatalogError(f"Duplicate {label} capability '{name}' ({source})")
        description = _require_string(table, "description", label=f"{label}[{index}]")
        input_schema = _require_schema(
            table,
            "input_schema",
            capability_name=name,
            source=source,
        )
        output_schema = _require_schema(
            table,
            "output_schema",
            capability_name=name,
            source=source,
        )
        by_name[name] = ToolDescriptor(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
        )
    return by_name


def _require_table(value: object, label: str, *, source: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CapabilityCatalogError(f"{label} must be a TOML table ({source})")
    return cast(dict[str, object], value)


def _require_list(value: object, label: str, *, source: str) -> list[object]:
    if not isinstance(value, list):
        raise CapabilityCatalogError(f"{label} must be an array of TOML tables ({source})")
    return cast(list[object], value)


def _require_string(data: dict[str, object], key: str, *, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise CapabilityCatalogError(f"{label}.{key} must be a string")
    normalized = value.strip()
    if not normalized:
        raise CapabilityCatalogError(f"{label}.{key} must be non-empty")
    return normalized


def _require_schema(
    data: dict[str, object],
    key: str,
    *,
    capability_name: str,
    source: str,
) -> dict[str, JsonValue]:
    schema = _require_json_table(
        data,
        key,
        label=capability_name,
        source=source,
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CapabilityCatalogError(
            f"Invalid JSON schema for capability '{capability_name}' field '{key}': {exc.message}"
        ) from exc
    return schema


def _require_json_table(
    data: dict[str, object],
    key: str,
    *,
    label: str,
    source: str,
) -> dict[str, JsonValue]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise CapabilityCatalogError(f"{label}.{key} must be a TOML table ({source})")
    table = cast(dict[str, JsonValue], value)
    ensure_json_value(table, label=f"{label}.{key}")
    return table


def _optional_json_table(
    data: dict[str, object],
    key: str,
    *,
    label: str,
    source: str,
) -> dict[str, JsonValue]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CapabilityCatalogError(f"{label}.{key} must be a TOML table ({source})")
    table = cast(dict[str, JsonValue], value)
    ensure_json_value(table, label=f"{label}.{key}")
    return table


def _normalized_data_query_registry(
    registry: dict[str, DataQueryDescriptor],
    *,
    label: str,
) -> dict[str, DataQueryDescriptor]:
    normalized: dict[str, DataQueryDescriptor] = {}
    for key, descriptor in registry.items():
        if not isinstance(key, str) or not key.strip():
            raise CapabilityCatalogError(f"{label} keys must be non-empty strings")
        if key in normalized:
            raise CapabilityCatalogError(f"{label} has duplicate key '{key}'")
        if descriptor.name != key:
            raise CapabilityCatalogError(
                f"{label} descriptor name mismatch: key='{key}' descriptor='{descriptor.name}'"
            )
        normalized[key] = descriptor
    return normalized


def _normalized_tool_registry(
    registry: dict[str, ToolDescriptor],
    *,
    label: str,
) -> dict[str, ToolDescriptor]:
    normalized: dict[str, ToolDescriptor] = {}
    for key, descriptor in registry.items():
        if not isinstance(key, str) or not key.strip():
            raise CapabilityCatalogError(f"{label} keys must be non-empty strings")
        if key in normalized:
            raise CapabilityCatalogError(f"{label} has duplicate key '{key}'")
        if descriptor.name != key:
            raise CapabilityCatalogError(
                f"{label} descriptor name mismatch: key='{key}' descriptor='{descriptor.name}'"
            )
        normalized[key] = descriptor
    return normalized


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "CapabilityCatalog",
    "CapabilityCatalogError",
    "load_capability_catalog",
    "load_capability_catalog_from_text",
]
