from __future__ import annotations

from runtime.support import discovered_agent
from test_helpers.capabilities import default_capability_catalog

from boxy_agent import (
    AgentEvent,
    AgentResult,
    memory_get,
    memory_set,
    terminate,
)
from boxy_agent.runtime import AgentRuntime


def test_session_and_persistent_memory_behaviors() -> None:
    def handle(context):
        if context.event.type != "start":
            return AgentResult(output={"status": "ignored", "event_type": context.event.type})

        session_raw = memory_get(context, "session_count")
        session_count = (session_raw if isinstance(session_raw, int) else 0) + 1

        persistent_raw = memory_get(context, "persistent_count", scope="persistent")
        persistent_count = (persistent_raw if isinstance(persistent_raw, int) else 0) + 1

        memory_set(context, "session_count", session_count)
        memory_set(context, "persistent_count", persistent_count, scope="persistent")

        return AgentResult(
            output={
                "session": memory_get(context, "session_count"),
                "persistent": memory_get(context, "persistent_count", scope="persistent"),
            }
        )

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(name="main", handler=handle, expected_event_types=("start",))
        },
    )

    first = runtime.run("main", {"type": "start"})
    second = runtime.run("main", {"type": "start"})

    assert first.last_output == {"session": 1, "persistent": 1}
    assert second.last_output == {"session": 1, "persistent": 2}


def test_private_delegation() -> None:
    def sub_agent(context):
        if context.event.type == "subtask":
            return AgentResult(output={"phase": 1})
        return AgentResult(output={"phase": 2})

    def main_agent(context):
        result = context.delegate_to_agent(
            "sub",
            AgentEvent(type="subtask", description="work", payload={}),
        )
        return AgentResult(output={"delegated_output": result.output})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=main_agent,
                agent_type="main",
            ),
            "sub": discovered_agent(
                name="sub", handler=sub_agent, expected_event_types=("subtask",)
            ),
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "idle"
    assert report.last_output == {"delegated_output": {"phase": 1}}


def test_private_delegated_termination_ends_parent() -> None:
    def sub_agent(context):
        terminate(context, "done")
        return AgentResult(output={"done": True})

    def main_agent(context):
        result = context.delegate_to_agent(
            "sub",
            AgentEvent(type="subtask", description="work", payload={}),
        )
        return AgentResult(output={"terminated": result.terminated})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=main_agent,
                agent_type="main",
            ),
            "sub": discovered_agent(
                name="sub", handler=sub_agent, expected_event_types=("subtask",)
            ),
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "terminated_by_agent"


def test_default_provider_shares_session_memory_across_delegation() -> None:
    def sub_agent(context):
        memory_set(context, "shared", "from-sub")
        return AgentResult(output={"status": "ok"})

    def main_agent(context):
        context.delegate_to_agent(
            "sub",
            AgentEvent(type="subtask", description="work", payload={}),
        )
        return AgentResult(output={"shared": memory_get(context, "shared")})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=main_agent,
                agent_type="main",
            ),
            "sub": discovered_agent(
                name="sub",
                handler=sub_agent,
                expected_event_types=("subtask",),
            ),
        },
    )

    report = runtime.run("main", {"type": "start"})
    assert report.last_output == {"shared": "from-sub"}
