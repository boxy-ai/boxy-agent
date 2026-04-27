from __future__ import annotations

import pytest
from test_helpers.capabilities import (
    DEFAULT_BOXY_TOOL_NAME,
    DEFAULT_DATA_QUERY_NAME,
    default_capability_catalog,
)

from boxy_agent.models import ToolDescriptor
from boxy_agent.runtime.providers import (
    BuiltinToolClient,
    PythonExecutionResult,
    StaticDataQueryClient,
    StaticToolClient,
    UnconfiguredClientError,
    UnconfiguredLlmClient,
)
from boxy_agent.runtime.providers.builtin_tools import _call_monty_run
from boxy_agent.types import JsonValue


def test_static_data_query_client_contract() -> None:
    catalog = default_capability_catalog()
    client = StaticDataQueryClient(
        descriptors=[catalog.data_queries[DEFAULT_DATA_QUERY_NAME]],
        query_results={
            DEFAULT_DATA_QUERY_NAME: [
                {
                    "chat_jid": "chat-1",
                    "before_ts_ms": None,
                    "before_message_id": None,
                    "next_before_ts_ms": None,
                    "next_before_message_id": None,
                    "has_more": False,
                    "count": 1,
                    "messages": [],
                }
            ]
        },
        execution_affinities={DEFAULT_DATA_QUERY_NAME: "main_thread"},
    )

    assert [item.name for item in client.list_data_queries()] == [DEFAULT_DATA_QUERY_NAME]
    assert client.data_query_execution_affinities() == {DEFAULT_DATA_QUERY_NAME: "main_thread"}
    assert client.query_data(
        DEFAULT_DATA_QUERY_NAME,
        {"chat_jid": "chat-1"},
        session_id="session-1",
        actor_principal="agent:test:session:session-1",
    ) == [
        {
            "chat_jid": "chat-1",
            "before_ts_ms": None,
            "before_message_id": None,
            "next_before_ts_ms": None,
            "next_before_message_id": None,
            "has_more": False,
            "count": 1,
            "messages": [],
        }
    ]

    with pytest.raises(UnconfiguredClientError, match="No data query result configured"):
        StaticDataQueryClient(
            descriptors=[catalog.data_queries[DEFAULT_DATA_QUERY_NAME]]
        ).query_data(
            DEFAULT_DATA_QUERY_NAME,
            {},
            session_id="session-1",
            actor_principal="agent:test:session:session-1",
        )


def test_static_tool_client_contract() -> None:
    catalog = default_capability_catalog()
    client = StaticToolClient(
        descriptors=[catalog.boxy_tools[DEFAULT_BOXY_TOOL_NAME]],
        execution_results={
            DEFAULT_BOXY_TOOL_NAME: {
                "status": "sent",
                "target_resolved": "chat-1",
                "message_ref": "out-1",
                "sent_at": "2026-01-01T00:00:00Z",
                "details": {},
            }
        },
        execution_affinities={DEFAULT_BOXY_TOOL_NAME: "main_thread"},
    )

    assert [item.name for item in client.list_tools()] == [DEFAULT_BOXY_TOOL_NAME]
    assert client.tool_execution_affinities() == {DEFAULT_BOXY_TOOL_NAME: "main_thread"}
    assert client.call_tool(
        DEFAULT_BOXY_TOOL_NAME,
        {
            "target": "chat-1",
            "message_content": "hello",
            "idempotency_key": "idemp-1",
        },
        session_id="session-1",
        actor_principal="agent:test:session:session-1",
    ) == {
        "status": "sent",
        "target_resolved": "chat-1",
        "message_ref": "out-1",
        "sent_at": "2026-01-01T00:00:00Z",
        "details": {},
    }

    with pytest.raises(UnconfiguredClientError, match="No tool result configured"):
        StaticToolClient(descriptors=[catalog.boxy_tools[DEFAULT_BOXY_TOOL_NAME]]).call_tool(
            DEFAULT_BOXY_TOOL_NAME,
            {},
            session_id="session-1",
            actor_principal="agent:test:session:session-1",
        )


def test_unconfigured_llm_client_rejects_usage() -> None:
    client = UnconfiguredLlmClient()

    with pytest.raises(UnconfiguredClientError, match="No LLM client configured"):
        client.chat_complete({"messages": []})


class _FakePythonExecutor:
    def execute(self, *, code: str, timeout_seconds: float) -> PythonExecutionResult:
        _ = code, timeout_seconds
        return PythonExecutionResult(result={"ok": True}, stdout="done", stderr="")


def test_builtin_tool_client_web_search_contract() -> None:
    catalog = default_capability_catalog()
    client = BuiltinToolClient(
        descriptors=[catalog.builtin_tools["web_search"]],
        python_executor=_FakePythonExecutor(),
    )

    assert [item.name for item in client.list_tools()] == ["web_search"]
    assert client.tool_execution_affinities() == {"web_search": "worker_thread_safe"}
    with pytest.raises(
        UnconfiguredClientError,
        match="web_search is not implemented in boxy-agent runtime; integrate via boxy-cloud",
    ):
        client.call_tool(
            "web_search",
            {"query": "boxy"},
            session_id="session-1",
            actor_principal="agent:test:session:session-1",
        )


def test_builtin_tool_client_python_exec_contract() -> None:
    catalog = default_capability_catalog()
    client = BuiltinToolClient(
        descriptors=[catalog.builtin_tools["python_exec"]],
        python_executor=_FakePythonExecutor(),
    )

    assert [item.name for item in client.list_tools()] == ["python_exec"]
    assert client.call_tool(
        "python_exec",
        {"code": "print('x')"},
        session_id="session-1",
        actor_principal="agent:test:session:session-1",
    ) == {
        "result": {"ok": True},
        "stdout": "done",
        "stderr": "",
    }


def test_builtin_tool_client_web_search_placeholder_validates_count() -> None:
    catalog = default_capability_catalog()
    client = BuiltinToolClient(
        descriptors=[catalog.builtin_tools["web_search"]],
        python_executor=_FakePythonExecutor(),
    )

    with pytest.raises(ValueError, match="field 'count' must be an integer"):
        client.call_tool(  # type: ignore[arg-type]
            "web_search",
            {"query": "boxy", "count": "1"},
            session_id="session-1",
            actor_principal="agent:test:session:session-1",
        )


def test_builtin_tool_client_filters_unknown_descriptors() -> None:
    client = BuiltinToolClient(
        descriptors=[ToolDescriptor(name="custom_tool", description="custom")],
        python_executor=_FakePythonExecutor(),
    )

    assert client.list_tools() == []
    with pytest.raises(
        UnconfiguredClientError,
        match="No built-in tool implementation configured",
    ):
        client.call_tool(
            "custom_tool",
            {},
            session_id="session-1",
            actor_principal="agent:test:session:session-1",
        )


def test_call_monty_run_does_not_retry_on_type_error() -> None:
    calls = {"count": 0}

    def fake_run(*, timeout_seconds):  # noqa: ANN001
        _ = timeout_seconds
        calls["count"] += 1
        raise TypeError("execution type error")

    with pytest.raises(TypeError, match="execution type error"):
        _call_monty_run(fake_run, timeout_seconds=1.0)

    assert calls["count"] == 1


def test_call_monty_run_does_not_force_empty_inputs() -> None:
    observed: dict[str, object | None] = {"inputs": "unset"}

    def fake_run(*, inputs=None, timeout_seconds=None):  # noqa: ANN001
        observed["inputs"] = inputs
        return {"ok": True, "timeout": timeout_seconds}

    result = _call_monty_run(fake_run, timeout_seconds=1.5)

    assert observed["inputs"] is None
    assert result == {"ok": True, "timeout": 1.5}


def test_builtin_tool_client_truncates_python_outputs() -> None:
    catalog = default_capability_catalog()
    long_stdout = "x" * 80_000
    long_stderr = "e" * 80_000
    big_result: JsonValue = {"payload": "r" * 400_000}

    class _LongOutputExecutor:
        def execute(self, *, code: str, timeout_seconds: float) -> PythonExecutionResult:
            _ = code, timeout_seconds
            return PythonExecutionResult(
                result=big_result,
                stdout=long_stdout,
                stderr=long_stderr,
            )

    client = BuiltinToolClient(
        descriptors=[catalog.builtin_tools["python_exec"]],
        python_executor=_LongOutputExecutor(),
    )
    output = client.call_tool(
        "python_exec",
        {"code": "print('x')"},
        session_id="session-1",
        actor_principal="agent:test:session:session-1",
    )

    assert isinstance(output, dict)
    assert isinstance(output["stdout"], str)
    assert isinstance(output["stderr"], str)
    assert len(output["stdout"]) <= 64 * 1024
    assert len(output["stderr"]) <= 64 * 1024
    assert output["stdout"].endswith("chars]")
    assert output["stderr"].endswith("chars]")
    result = output["result"]
    assert isinstance(result, dict)
    assert result["truncated"] is True
    assert result["max_size_bytes"] == 256 * 1024
