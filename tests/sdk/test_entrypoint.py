from __future__ import annotations

from boxy_agent import AgentExecutionContext, AgentResult, agent_main
from boxy_agent.sdk.decorators import get_entrypoint_metadata, is_canonical_entrypoint


@agent_main
def _sample_main(_exec_ctx: AgentExecutionContext) -> AgentResult:
    return AgentResult(output={"ok": True})


def test_agent_main_decorator_marks_function() -> None:
    metadata = get_entrypoint_metadata(_sample_main)
    assert metadata is not None
    assert metadata.is_canonical_main is True
    assert is_canonical_entrypoint(_sample_main)


def test_agent_main_supports_call_form() -> None:
    @agent_main()
    def handle(_exec_ctx: AgentExecutionContext) -> AgentResult:
        return AgentResult(output={"ok": True})

    assert get_entrypoint_metadata(handle) is not None


def test_undecorated_function_has_no_metadata() -> None:
    def handle(_exec_ctx: AgentExecutionContext) -> AgentResult:
        return AgentResult(output={"ok": True})

    assert get_entrypoint_metadata(handle) is None
    assert not is_canonical_entrypoint(handle)
