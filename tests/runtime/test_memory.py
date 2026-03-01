from __future__ import annotations

from runtime.support import discovered_agent
from test_helpers.capabilities import default_capability_catalog

from boxy_agent import (
    AgentResult,
    memory_get,
    memory_set,
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
