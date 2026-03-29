"""Minimal reference data-mining agent."""

from __future__ import annotations

from boxy_agent.sdk import data_queries, decorators, events, models


def _chat_context_message_count(result: object) -> int:
    if not isinstance(result, dict):
        return 0
    data = result.get("data")
    if not isinstance(data, dict):
        return 0
    messages = data.get("messages")
    if not isinstance(messages, list):
        return 0
    return len(messages)


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

    chat_context = data_queries.query(
        exec_ctx,
        "whatsapp.chat_context",
        {"chat_jid": chat_jid_value.strip()},
    )
    message_count = _chat_context_message_count(chat_context)
    events.emit(
        exec_ctx,
        "insight.generated",
        description="Generated a minimal chat insight",
        payload={"message_count": message_count},
    )
    return models.AgentResult(
        output={
            "status": "completed",
            "message_count": message_count,
        }
    )
