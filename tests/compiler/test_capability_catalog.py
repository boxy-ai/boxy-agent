from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_helpers.capabilities import (
    DEFAULT_BOXY_TOOL_NAME,
    DEFAULT_BUILTIN_TOOL_NAME,
    DEFAULT_DATA_QUERY_NAME,
    default_capability_catalog,
)

from boxy_agent.capabilities import (
    CapabilityCatalogError,
    load_capability_catalog,
    load_packaged_builtin_capability_catalog,
    load_packaged_capability_catalog,
)


def test_default_capability_catalog_contains_expected_capabilities() -> None:
    catalog = default_capability_catalog()
    assert DEFAULT_DATA_QUERY_NAME in catalog.data_queries
    assert DEFAULT_BOXY_TOOL_NAME in catalog.boxy_tools
    assert DEFAULT_BUILTIN_TOOL_NAME in catalog.builtin_tools
    assert "python_exec" in catalog.builtin_tools


def test_load_capability_catalog_rejects_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "bad-catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_queries": [
                    {
                        "name": "custom.messages",
                        "description": "Custom query",
                        "input_schema": {"type": "object", "properties": "invalid"},
                        "output_schema": {"type": "array", "items": {}},
                    }
                ],
                "boxy_tools": [
                    {
                        "name": "custom.send",
                        "description": "Custom tool",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    }
                ],
                "builtin_tools": [
                    {
                        "name": "custom.search",
                        "description": "Custom built-in",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CapabilityCatalogError, match="Invalid JSON schema"):
        load_capability_catalog(path)


def test_load_capability_catalog_from_json_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "data_queries": [
                    {
                        "name": "custom.messages",
                        "description": "Custom query",
                        "input_schema": {
                            "type": "object",
                            "properties": {"fts": {"type": "string"}},
                        },
                        "output_schema": {"type": "array", "items": {"type": "object"}},
                        "max_limit": 25,
                    }
                ],
                "boxy_tools": [
                    {
                        "name": "custom.send",
                        "description": "Custom tool",
                        "input_schema": {
                            "type": "object",
                            "properties": {"body": {"type": "string"}},
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"status": {"type": "string"}},
                        },
                        "side_effect": True,
                    }
                ],
                "builtin_tools": [
                    {
                        "name": "custom.search",
                        "description": "Custom built-in",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                        "output_schema": {"type": "object"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = load_capability_catalog(path)

    assert list(catalog.data_queries) == ["custom.messages"]
    assert list(catalog.boxy_tools) == ["custom.send"]
    assert list(catalog.builtin_tools) == ["custom.search"]
    assert catalog.data_queries["custom.messages"].max_limit == 25
    assert catalog.boxy_tools["custom.send"].side_effect is True


def test_packaged_builtin_catalog_carries_builtin_tool_usage_guidance() -> None:
    catalog = load_packaged_builtin_capability_catalog()

    python_exec = catalog.builtin_tools["python_exec"]
    assert "Do not use it to fetch network data, call Boxy tools" in python_exec.description

    web_search = catalog.builtin_tools["web_search"]
    assert (
        "Do not use for private connector or locally ingested user data" in web_search.description
    )


def test_packaged_catalog_carries_google_chat_semantic_fallback_guidance() -> None:
    catalog = load_packaged_capability_catalog()

    descriptor = catalog.data_queries["google_chat.search_messages_semantic_local"]
    assert "embedding_ready=false" in descriptor.description
    assert "search_spaces_local" in descriptor.description
    assert "get_space_messages_local" in descriptor.description
