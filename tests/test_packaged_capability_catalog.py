from __future__ import annotations

from boxy_agent.capabilities import (
    load_packaged_builtin_capability_catalog,
    load_packaged_capability_catalog,
)


def test_packaged_capability_catalog_contains_shipping_connector_and_builtin_capabilities() -> None:
    catalog = load_packaged_capability_catalog()

    assert "whatsapp.chat_context" in catalog.data_queries
    assert "whatsapp.send_message" in catalog.boxy_tools
    assert "web_search" in catalog.builtin_tools


def test_packaged_builtin_catalog_is_builtin_only() -> None:
    catalog = load_packaged_builtin_capability_catalog()

    assert catalog.data_queries == {}
    assert catalog.boxy_tools == {}
    assert "web_search" in catalog.builtin_tools
