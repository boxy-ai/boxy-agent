"""Minimal canonical main agent with an observe-plan-act loop."""

from __future__ import annotations

from boxy_agent.private_sdk import PrivateAgentExecutionContext
from boxy_agent.sdk import data_queries, decorators, models

AUTOMATION_AGENT_NAME = "canonical-automation-email-agent"


@decorators.agent_main
def handle(exec_ctx: PrivateAgentExecutionContext) -> models.AgentResult:
    """Observe, plan, and act for a single trigger event."""
    if exec_ctx.event.type != "start":
        return models.AgentResult()

    phase = "observe"
    observation: list[models.JsonValue] = []
    plan: dict[str, models.JsonValue] = {}

    while True:
        if phase == "observe":
            observation = data_queries.query(exec_ctx, "gmail.messages", {"limit": 1})
            phase = "plan"
            continue

        if phase == "plan":
            requested_mode = exec_ctx.event.payload.get("mode")
            action = "delegate" if requested_mode == "delegate" else "report"
            plan = {"action": action}
            phase = "act"
            continue

        if plan["action"] == "delegate":
            delegated = exec_ctx.delegate_to_agent(
                AUTOMATION_AGENT_NAME,
                models.AgentEvent(
                    type="email.reply_request",
                    payload={"recipient": "alex@example.com"},
                ),
            )
            result: dict[str, models.JsonValue] = {
                "mode": "delegate",
                "delegated_output": delegated.output,
            }
        else:
            result = {
                "mode": "report",
                "message_count": len(observation),
            }

        return models.AgentResult(output={"phase": "complete", "result": result})
