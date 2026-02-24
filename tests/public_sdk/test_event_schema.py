from __future__ import annotations

from typing import cast

import pytest

from boxy_agent import AgentCapabilities, AgentEvent
from boxy_agent.types import JsonValue


def test_agent_event_accepts_required_envelope() -> None:
    event = AgentEvent(
        type="user.message",
        description="User sent a message",
        payload={"text": "hello", "source": "chat"},
    )

    assert event.type == "user.message"
    assert event.description == "User sent a message"
    assert event.payload["text"] == "hello"


def test_agent_event_rejects_empty_type() -> None:
    with pytest.raises(ValueError):
        AgentEvent(type="", description="desc", payload={})


def test_agent_event_rejects_non_json_payload_value() -> None:
    with pytest.raises(TypeError):
        AgentEvent(
            type="event",
            description="desc",
            payload=cast(dict[str, JsonValue], {"bad": object()}),
        )


def test_agent_capabilities_normalizes_event_emitters() -> None:
    capabilities = AgentCapabilities(event_emitters=frozenset({" insight.generated "}))

    assert capabilities.event_emitters == frozenset({"insight.generated"})
