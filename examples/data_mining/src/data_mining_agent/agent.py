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

    chat_jid_value = exec_ctx.event.payload.get("chat_jid", "chat-1")
    if not isinstance(chat_jid_value, str) or not chat_jid_value.strip():
        raise ValueError("chat_jid payload field must be a non-empty string")

    messages = data_queries.query(
        exec_ctx,
        "whatsapp.chat_context",
        {"chat_jid": chat_jid_value.strip()},
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
