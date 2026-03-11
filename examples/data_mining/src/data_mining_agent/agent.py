"""Minimal reference data-mining agent."""

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

    chat_id_value = exec_ctx.event.payload.get("chat_id", "chat-1")
    if not isinstance(chat_id_value, str) or not chat_id_value.strip():
        raise ValueError("chat_id payload field must be a non-empty string")

    messages = data_queries.query(
        exec_ctx,
        "whatsapp.chat_context",
        {"chat_id": chat_id_value.strip()},
    )
    events.emit(
        exec_ctx,
        "insight.generated",
        description="Generated a minimal chat insight",
        payload={"message_count": len(messages)},
    )
    return models.AgentResult(
        output={
            "status": "completed",
            "message_count": len(messages),
        }
    )
