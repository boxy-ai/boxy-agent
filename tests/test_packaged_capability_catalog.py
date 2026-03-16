from __future__ import annotations

from boxy_agent.capabilities import (
    load_packaged_builtin_capability_catalog,
    load_packaged_capability_catalog,
)


def test_packaged_capability_catalog_contains_shipping_connector_and_builtin_capabilities() -> None:
    catalog = load_packaged_capability_catalog()

    assert "google_gmail.search_threads_local" in catalog.data_queries
    assert "google_gmail.get_thread_local" in catalog.data_queries
    assert "google_gmail.gmail_search_threads" in catalog.boxy_tools
    assert catalog.boxy_tools["google_gmail.gmail_search_threads"].side_effect is False
    assert "whatsapp.chat_context" in catalog.data_queries
    assert "whatsapp.send_message" in catalog.boxy_tools
    assert catalog.boxy_tools["whatsapp.send_message"].side_effect is True
    assert "reference.reference_echo" not in catalog.boxy_tools
    assert "web_search" in catalog.builtin_tools


def test_packaged_builtin_catalog_is_builtin_only() -> None:
    catalog = load_packaged_builtin_capability_catalog()

    assert catalog.data_queries == {}
    assert catalog.boxy_tools == {}
    assert "web_search" in catalog.builtin_tools


def test_packaged_python_exec_description_warns_about_constraints() -> None:
    catalog = load_packaged_builtin_capability_catalog()

    description = catalog.builtin_tools["python_exec"].description.lower()
    assert "constrained environment" in description
    assert "no network access" in description
    assert "small local calculations" in description
