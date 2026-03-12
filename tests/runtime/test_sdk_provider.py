from __future__ import annotations

from runtime.support import discovered_agent
from test_helpers.capabilities import default_capability_catalog
from test_helpers.sdk_provider import MockAgentSdkProvider

from boxy_agent import (
    AgentCapabilities,
    AgentEvent,
    AgentResult,
    emit_event,
    llm_chat_complete,
    memory_get,
    memory_set,
    trace,
)
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.models import EventQueueItem
from boxy_agent.runtime.providers import CoreAgentSdkProvider
from boxy_agent.sdk.interfaces import LlmClient
from boxy_agent.types import JsonValue


class _RecordingProvider(MockAgentSdkProvider):
    def __init__(self) -> None:
        super().__init__()
        self.created_sessions: list[tuple[str, str]] = []
        self.closed_sessions: list[str] = []
        self.published_events: list[EventQueueItem] = []
        self.recorded_traces: list[tuple[str, str, str]] = []

    def create_session(self, *, agent_name: str, event: AgentEvent) -> str:
        session_id = super().create_session(agent_name=agent_name, event=event)
        self.created_sessions.append((agent_name, event.type))
        return session_id

    def close_session(self, session_id: str) -> None:
        self.closed_sessions.append(session_id)

    def publish_event(self, event: EventQueueItem) -> None:
        self.published_events.append(event)

    def record_trace(
        self,
        *,
        agent_name: str,
        session_id: str,
        event: AgentEvent,
        trace_name: str,
        payload: dict[str, JsonValue],
    ) -> None:
        _ = payload
        self.recorded_traces.append((agent_name, session_id, f"{event.type}:{trace_name}"))


class _RecordingLlmClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, JsonValue]] = []

    def chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        self.requests.append(request)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class _SessionAwareLlmProvider(MockAgentSdkProvider):
    def __init__(self, *, llm_client: LlmClient) -> None:
        super().__init__(llm_client=llm_client)
        self.llm_client_calls: list[tuple[str, str]] = []

    def llm_client(self, *, agent_name: str, session_id: str) -> LlmClient:
        self.llm_client_calls.append((agent_name, session_id))
        return super().llm_client(agent_name=agent_name, session_id=session_id)


class _FakeCoreClient:
    def __init__(self) -> None:
        self._next_session = 1
        self.created_session_metadata: list[JsonValue | None] = []
        self.closed_sessions: list[str] = []
        self.memory: dict[tuple[str, str | None, str], JsonValue] = {}
        self.enqueued_events: list[tuple[JsonValue, str]] = []

    def create_session(self, *, metadata: JsonValue | None = None) -> str:
        session_id = f"core-session-{self._next_session}"
        self._next_session += 1
        self.created_session_metadata.append(metadata)
        return session_id

    def close_session(self, session_id: str) -> None:
        self.closed_sessions.append(session_id)

    def set_memory(
        self,
        *,
        scope: str,
        key: str,
        value: JsonValue,
        session_id: str | None = None,
    ) -> None:
        self.memory[(scope, session_id, key)] = value

    def get_memory(
        self,
        *,
        scope: str,
        key: str,
        session_id: str | None = None,
    ) -> JsonValue | None:
        return self.memory.get((scope, session_id, key))

    def delete_memory(
        self,
        *,
        scope: str,
        key: str,
        session_id: str | None = None,
    ) -> None:
        self.memory.pop((scope, session_id, key), None)

    def enqueue_event(
        self,
        payload: JsonValue,
        *,
        topic: str = "default",
        available_at: str | None = None,
    ) -> str:
        _ = available_at
        self.enqueued_events.append((payload, topic))
        return f"evt-{len(self.enqueued_events)}"


def test_runtime_uses_injected_sdk_provider() -> None:
    provider = _RecordingProvider()

    def handle(exec_ctx):
        memory_set(exec_ctx, "counter", 1)
        trace(exec_ctx, "main.test.trace", {"iteration_index": 1})
        emit_event(exec_ctx, "followup", payload={"step": 2})
        return AgentResult(output={"counter": memory_get(exec_ctx, "counter")})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        sdk_provider=provider,
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(
                    event_emitters=frozenset({"followup"}),
                ),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.last_output == {"counter": 1}
    assert provider.created_sessions == [("main", "start")]
    assert provider.closed_sessions == [report.session_id]
    assert [item.event.type for item in provider.published_events] == ["followup"]
    assert provider.recorded_traces == [("main", report.session_id, "start:main.test.trace")]


def test_core_provider_uses_core_for_sessions_memory_and_events() -> None:
    core_client = _FakeCoreClient()
    provider = CoreAgentSdkProvider(core_client=core_client, event_topic="agent-events")

    def handle(exec_ctx):
        memory_set(exec_ctx, "session_key", "session-value")
        memory_set(exec_ctx, "persistent_key", "persistent-value", scope="persistent")
        emit_event(exec_ctx, "followup", payload={"k": "v"})
        return AgentResult(
            output={
                "session": memory_get(exec_ctx, "session_key"),
                "persistent": memory_get(exec_ctx, "persistent_key", scope="persistent"),
            }
        )

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        sdk_provider=provider,
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(event_emitters=frozenset({"followup"})),
            )
        },
    )

    report = runtime.run("main", {"type": "start", "description": "kickoff"})
    runtime.queue_event({"type": "connector.email", "payload": {"id": "m-1"}}, source="connector")

    assert report.session_id == "core-session-1"
    assert report.last_output == {
        "session": "session-value",
        "persistent": "persistent-value",
    }

    assert core_client.created_session_metadata == [
        {
            "agent_name": "main",
            "event": {"type": "start", "description": "kickoff"},
        }
    ]
    assert core_client.closed_sessions == ["core-session-1"]
    assert core_client.memory[("session", "core-session-1", "session_key")] == "session-value"
    assert core_client.memory[("persistent", None, "persistent_key")] == "persistent-value"

    assert len(core_client.enqueued_events) == 2
    first_payload, first_topic = core_client.enqueued_events[0]
    assert first_topic == "agent-events"
    assert first_payload == {
        "target_kind": "main_agent",
        "mode": "workflow",
        "trigger_kind": "root",
        "event": {"type": "followup", "description": "", "payload": {"k": "v"}},
        "source": "agent",
        "source_agent": "main",
        "source_session_id": "core-session-1",
    }

    second_payload, second_topic = core_client.enqueued_events[1]
    assert second_topic == "agent-events"
    assert second_payload == {
        "target_kind": "main_agent",
        "mode": "workflow",
        "trigger_kind": "root",
        "event": {
            "type": "connector.email",
            "description": "",
            "payload": {"id": "m-1"},
        },
        "source": "connector",
    }


def test_runtime_requests_llm_client_with_bound_session() -> None:
    llm_client = _RecordingLlmClient()
    provider = _SessionAwareLlmProvider(llm_client=llm_client)

    def handle(exec_ctx):
        return AgentResult(
            output=llm_chat_complete(
                exec_ctx,
                {
                    "model": "gpt-4.1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
        )

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        sdk_provider=provider,
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                capabilities=AgentCapabilities(),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert provider.llm_client_calls == [("main", report.session_id)]
    assert llm_client.requests == [
        {
            "model": "gpt-4.1",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ]
