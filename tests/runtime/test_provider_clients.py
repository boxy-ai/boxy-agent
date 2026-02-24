from __future__ import annotations

import pytest
from test_helpers.capabilities import default_capability_catalog

from boxy_agent.runtime.providers import (
    StaticDataQueryClient,
    StaticToolClient,
    UnconfiguredClientError,
    UnconfiguredLlmClient,
)


def test_static_data_query_client_contract() -> None:
    catalog = default_capability_catalog()
    client = StaticDataQueryClient(
        descriptors=[catalog.data_queries["gmail.messages"]],
        query_results={"gmail.messages": [{"id": "row-1"}]},
    )

    assert [item.name for item in client.list_data_queries()] == ["gmail.messages"]
    assert client.query_data("gmail.messages", {"fts": "alpha"}) == [{"id": "row-1"}]

    with pytest.raises(UnconfiguredClientError, match="No data query result configured"):
        StaticDataQueryClient(descriptors=[catalog.data_queries["gmail.messages"]]).query_data(
            "gmail.messages", {}
        )


def test_static_tool_client_contract() -> None:
    catalog = default_capability_catalog()
    client = StaticToolClient(
        descriptors=[catalog.boxy_tools["gmail.send_message"]],
        execution_results={"gmail.send_message": {"status": "sent", "message_id": "out-1"}},
    )

    assert [item.name for item in client.list_tools()] == ["gmail.send_message"]
    assert client.call_tool("gmail.send_message", {"to": ["a@example.com"]}) == {
        "status": "sent",
        "message_id": "out-1",
    }

    with pytest.raises(UnconfiguredClientError, match="No tool result configured"):
        StaticToolClient(descriptors=[catalog.boxy_tools["gmail.send_message"]]).call_tool(
            "gmail.send_message",
            {},
        )


def test_unconfigured_llm_client_rejects_usage() -> None:
    client = UnconfiguredLlmClient()

    with pytest.raises(UnconfiguredClientError, match="No LLM client configured"):
        client.complete("hello")
