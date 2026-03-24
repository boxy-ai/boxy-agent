from __future__ import annotations

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
)


def test_default_capability_catalog_contains_expected_capabilities() -> None:
    catalog = default_capability_catalog()
    assert DEFAULT_DATA_QUERY_NAME in catalog.data_queries
    assert DEFAULT_BOXY_TOOL_NAME in catalog.boxy_tools
    assert DEFAULT_BUILTIN_TOOL_NAME in catalog.builtin_tools
    assert "python_exec" in catalog.builtin_tools


def test_load_capability_catalog_rejects_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "bad-catalog.toml"
    path.write_text(
        """
schema_version = 1

[[data_queries]]
name = "custom.messages"
description = "Custom query"
input_schema = { type = "object", properties = "invalid" }
output_schema = { type = "array", items = {} }

[[boxy_tools]]
name = "custom.send"
description = "Custom tool"
input_schema = { type = "object" }
output_schema = { type = "object" }

[[builtin_tools]]
name = "custom.search"
description = "Custom built-in"
input_schema = { type = "object" }
output_schema = { type = "object" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(CapabilityCatalogError, match="Invalid JSON schema"):
        load_capability_catalog(path)


def test_load_capability_catalog_from_toml_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(
        """
schema_version = 1

[[data_queries]]
name = "custom.messages"
description = "Custom query"
input_schema = { type = "object", properties = { fts = { type = "string" } } }
output_schema = { type = "array", items = { type = "object" } }
query_capabilities = { source_kind = "local_ingested", selection_group = "custom.messages.search" }

[[boxy_tools]]
name = "custom.send"
description = "Custom tool"
input_schema = { type = "object", properties = { body = { type = "string" } } }
output_schema = { type = "object", properties = { status = { type = "string" } } }
side_effect = true
tool_capabilities = { source_kind = "live_provider", selection_group = "custom.messages.send" }

[[builtin_tools]]
name = "custom.search"
description = "Custom built-in"
input_schema = { type = "object", properties = { query = { type = "string" } } }
output_schema = { type = "object" }
""".strip(),
        encoding="utf-8",
    )

    catalog = load_capability_catalog(path)

    assert list(catalog.data_queries) == ["custom.messages"]
    assert list(catalog.boxy_tools) == ["custom.send"]
    assert list(catalog.builtin_tools) == ["custom.search"]
    assert catalog.data_queries["custom.messages"].query_capabilities == {
        "source_kind": "local_ingested",
        "selection_group": "custom.messages.search",
    }
    assert catalog.boxy_tools["custom.send"].side_effect is True
    assert catalog.boxy_tools["custom.send"].tool_capabilities == {
        "source_kind": "live_provider",
        "selection_group": "custom.messages.send",
    }
