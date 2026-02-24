"""Minimal canonical data-mining agent."""

from __future__ import annotations

from boxy_agent.sdk import data_queries, decorators, events, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    """Run a single sequential mining pass."""
    if exec_ctx.event.type != "scheduled.interval":
        return models.AgentResult(
            output={
                "status": "ignored",
                "event_type": exec_ctx.event.type,
            }
        )

    messages = data_queries.query(exec_ctx, "gmail.messages", {"limit": 1})
    events.emit(
        exec_ctx,
        "insight.generated",
        description="Generated a minimal inbox insight",
        payload={"message_count": len(messages)},
    )
    return models.AgentResult(
        output={
            "status": "completed",
            "message_count": len(messages),
        }
    )
