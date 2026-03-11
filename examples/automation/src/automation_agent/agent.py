"""Minimal reference automation agent."""

from __future__ import annotations

from boxy_agent.sdk import boxy_tools, data_queries, decorators, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    """Run a single sequential automation pass."""
    if exec_ctx.event.type != "chat.reply_request":
        return models.AgentResult(
            output={
                "status": "ignored",
                "event_type": exec_ctx.event.type,
            }
        )

    target_value = exec_ctx.event.payload.get("target")
    chat_id_value = exec_ctx.event.payload.get("chat_id")
    if not isinstance(target_value, str) or not target_value.strip():
        raise ValueError("target payload field must be a non-empty string")
    if not isinstance(chat_id_value, str) or not chat_id_value.strip():
        raise ValueError("chat_id payload field must be a non-empty string")
    target = target_value.strip()
    chat_id = chat_id_value.strip()

    messages = data_queries.query(exec_ctx, "whatsapp.chat_context", {"chat_id": chat_id})
    send_result = boxy_tools.call(
        exec_ctx,
        "whatsapp.send_message",
        {
            "target": target,
            "message_content": "Thanks for the update.",
            "idempotency_key": f"reference-{exec_ctx.session_id}",
        },
    )

    return models.AgentResult(
        output={
            "status": "completed",
            "target": target,
            "message_count": len(messages),
            "send_result": send_result,
        }
    )
