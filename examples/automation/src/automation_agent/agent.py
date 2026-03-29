"""Minimal reference automation agent."""

from __future__ import annotations

from boxy_agent.sdk import boxy_tools, data_queries, decorators, models


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
    """Run a single sequential automation pass."""
    if exec_ctx.event.type != "chat.reply_request":
        return models.AgentResult(
            output={
                "status": "ignored",
                "event_type": exec_ctx.event.type,
            }
        )

    target_value = exec_ctx.event.payload.get("target")
    chat_jid_value = exec_ctx.event.payload.get("chat_jid")
    if not isinstance(target_value, str) or not target_value.strip():
        raise ValueError("target payload field must be a non-empty string")
    if not isinstance(chat_jid_value, str) or not chat_jid_value.strip():
        raise ValueError("chat_jid payload field must be a non-empty string")
    target = target_value.strip()
    chat_jid = chat_jid_value.strip()

    chat_context = data_queries.query(exec_ctx, "whatsapp.chat_context", {"chat_jid": chat_jid})
    message_count = _chat_context_message_count(chat_context)
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
            "message_count": message_count,
            "send_result": send_result,
        }
    )
