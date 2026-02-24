"""Minimal canonical automation agent."""

from __future__ import annotations

from boxy_agent.sdk import boxy_tools, data_queries, decorators, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    """Run a single sequential automation pass."""
    if exec_ctx.event.type != "email.reply_request":
        return models.AgentResult(
            output={
                "status": "ignored",
                "event_type": exec_ctx.event.type,
            }
        )

    recipient_value = exec_ctx.event.payload.get("recipient")
    if not isinstance(recipient_value, str) or not recipient_value.strip():
        raise ValueError("recipient payload field must be a non-empty string")
    recipient = recipient_value.strip()

    messages = data_queries.query(exec_ctx, "gmail.messages", {"limit": 1})
    send_result = boxy_tools.call(
        exec_ctx,
        "gmail.send_message",
        {
            "to": [recipient],
            "subject": "Re: update",
            "body": "Thanks for the update.",
        },
    )

    return models.AgentResult(
        output={
            "status": "completed",
            "recipient": recipient,
            "message_count": len(messages),
            "send_result": send_result,
        }
    )
