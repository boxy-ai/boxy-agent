from __future__ import annotations

from runtime.support import discovered_agent
from test_helpers.capabilities import default_capability_catalog

from boxy_agent import AgentCapabilities, AgentResult, emit_event, trace
from boxy_agent.runtime import AgentRuntime


def test_run_handles_only_the_trigger_event() -> None:
    def handle(exec_ctx):
        if exec_ctx.event.type == "start":
            emit_event(
                exec_ctx,
                "followup",
                description="Follow-up work",
                payload={"step": 2},
            )
            return AgentResult(output={"step": 1})
        trace(exec_ctx, "handled.followup", {"step": 2})
        return AgentResult(output={"step": 2})

    runtime = AgentRuntime(
        capability_catalog=default_capability_catalog(),
        agent_registry_loader=lambda: {
            "main": discovered_agent(
                name="main",
                handler=handle,
                expected_event_types=("start", "followup"),
                capabilities=AgentCapabilities(
                    event_emitters=frozenset({"followup"}),
                ),
            )
        },
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "idle"
    assert report.last_output == {"step": 1}
    queued = runtime.drain_event_queue()
    assert [item.event.type for item in queued] == ["followup"]
    assert [item.source for item in queued] == ["agent"]
    assert any(item.trace_name == "step.start" for item in report.traces)
    assert all(item.trace_name != "handled.followup" for item in report.traces)
