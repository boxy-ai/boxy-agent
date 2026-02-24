from __future__ import annotations

from pathlib import Path

import pytest
from test_helpers.capabilities import default_capability_catalog

from boxy_agent.capabilities import (
    CapabilityCatalogError,
    load_capability_catalog,
)


def test_default_capability_catalog_contains_expected_capabilities() -> None:
    catalog = default_capability_catalog()
    assert "gmail.messages" in catalog.data_queries
    assert "gmail.send_message" in catalog.boxy_tools
    assert "web_search" in catalog.builtin_tools


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

[[boxy_tools]]
name = "custom.send"
description = "Custom tool"
input_schema = { type = "object", properties = { body = { type = "string" } } }
output_schema = { type = "object", properties = { status = { type = "string" } } }

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
