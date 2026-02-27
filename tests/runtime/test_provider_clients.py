from __future__ import annotations

import pytest
from test_helpers.capabilities import default_capability_catalog

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
        descriptors=[catalog.data_queries["gmail.messages"]],
        query_results={"gmail.messages": [{"id": "row-1"}]},
    )

    assert [item.name for item in client.list_data_queries()] == ["gmail.messages"]
    assert client.query_data("gmail.messages", {"fts": "alpha"}) == [{"id": "row-1"}]

    with pytest.raises(UnconfiguredClientError, match="No data query result configured"):
        StaticDataQueryClient(descriptors=[catalog.data_queries["gmail.messages"]]).query_data(
            "gmail.messages", {}
        )


def test_static_tool_client_contract() -> None:
    catalog = default_capability_catalog()
    client = StaticToolClient(
        descriptors=[catalog.boxy_tools["gmail.send_message"]],
        execution_results={"gmail.send_message": {"status": "sent", "message_id": "out-1"}},
    )

    assert [item.name for item in client.list_tools()] == ["gmail.send_message"]
    assert client.call_tool("gmail.send_message", {"to": ["a@example.com"]}) == {
        "status": "sent",
        "message_id": "out-1",
    }

    with pytest.raises(UnconfiguredClientError, match="No tool result configured"):
        StaticToolClient(descriptors=[catalog.boxy_tools["gmail.send_message"]]).call_tool(
            "gmail.send_message",
            {},
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
    with pytest.raises(
        UnconfiguredClientError,
        match="web_search is not implemented in boxy-agent runtime; integrate via boxy-cloud",
    ):
        client.call_tool("web_search", {"query": "boxy"})


def test_builtin_tool_client_python_exec_contract() -> None:
    catalog = default_capability_catalog()
    client = BuiltinToolClient(
        descriptors=[catalog.builtin_tools["python_exec"]],
        python_executor=_FakePythonExecutor(),
    )

    assert [item.name for item in client.list_tools()] == ["python_exec"]
    assert client.call_tool("python_exec", {"code": "print('x')"}) == {
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
        client.call_tool("web_search", {"query": "boxy", "count": "1"})  # type: ignore[arg-type]


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
        client.call_tool("custom_tool", {})


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
    output = client.call_tool("python_exec", {"code": "print('x')"})

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
