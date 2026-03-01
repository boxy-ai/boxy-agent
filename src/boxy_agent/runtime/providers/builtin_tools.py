"""Built-in tool implementations for web search and Python execution."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from boxy_agent.models import ToolDescriptor
from boxy_agent.runtime.providers.clients import BuiltinToolError, UnconfiguredClientError
from boxy_agent.sdk.interfaces import ToolClient
from boxy_agent.types import JsonValue, is_json_value

_BRAVE_DEFAULT_RESULT_COUNT = 5
_BRAVE_MAX_RESULT_COUNT = 20
_PYTHON_DEFAULT_TIMEOUT_SECONDS = 5.0
_PYTHON_MAX_TIMEOUT_SECONDS = 30.0
_PYTHON_MAX_STD_STREAM_CHARS = 64 * 1024
_PYTHON_MAX_RESULT_BYTES = 256 * 1024
_PYTHON_RESULT_PREVIEW_CHARS = 4096


@dataclass(frozen=True)
class PythonExecutionResult:
    result: JsonValue | None
    stdout: str
    stderr: str


class PythonExecutor(Protocol):
    def execute(self, *, code: str, timeout_seconds: float) -> PythonExecutionResult: ...


class MontyPythonExecutor:
    """Python code executor backed by pydantic-monty."""

    def execute(self, *, code: str, timeout_seconds: float) -> PythonExecutionResult:
        try:
            # Optional dependency: load lazily so runtimes without Monty can still start.
            import pydantic_monty
        except ImportError as exc:
            raise UnconfiguredClientError(
                "pydantic-monty is not installed; install it to enable python_exec"
            ) from exc

        try:
            monty = pydantic_monty.Monty(code, script_name="boxy_builtin_python_exec.py")
        except TypeError:
            monty = pydantic_monty.Monty(code)
        except Exception as exc:  # noqa: BLE001
            raise BuiltinToolError(f"Failed to initialize Monty runtime: {exc}") from exc

        run = getattr(monty, "run", None)
        if not callable(run):
            raise BuiltinToolError("Installed pydantic-monty does not expose Monty.run")

        raw_result: object
        try:
            raw_result = _call_monty_run(run, timeout_seconds=timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            raise BuiltinToolError(f"Monty execution failed: {exc}") from exc

        output = _coerce_json_value(getattr(raw_result, "output", raw_result))
        stdout = _coerce_string(getattr(raw_result, "stdout", ""))
        stderr = _coerce_string(getattr(raw_result, "stderr", ""))
        return PythonExecutionResult(result=output, stdout=stdout, stderr=stderr)


class BuiltinToolClient(ToolClient):
    """Tool client that executes runtime-owned built-in tools."""

    def __init__(
        self,
        *,
        descriptors: Sequence[ToolDescriptor] | None = None,
        python_executor: PythonExecutor | None = None,
    ) -> None:
        source_descriptors = descriptors or []
        self._descriptors = {descriptor.name: descriptor for descriptor in source_descriptors}
        self._python_executor = python_executor or MontyPythonExecutor()
        self._supported_handlers: dict[str, Callable[[dict[str, JsonValue]], JsonValue]] = {
            "web_search": self._call_web_search,
            "python_exec": self._call_python_exec,
        }
        self._handlers = {
            name: self._supported_handlers[name]
            for name in self._descriptors
            if name in self._supported_handlers
        }

    def list_tools(self) -> list[ToolDescriptor]:
        return [self._descriptors[name] for name in self._handlers]

    def call_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        if name not in self._descriptors:
            raise UnconfiguredClientError(f"Unknown built-in tool descriptor '{name}'")

        handler = self._handlers.get(name)
        if handler is None:
            raise UnconfiguredClientError(
                f"No built-in tool implementation configured for descriptor '{name}'"
            )
        return handler(params)

    def _call_web_search(self, params: dict[str, JsonValue]) -> JsonValue:
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("web_search requires non-empty string field 'query'")

        raw_count = params.get("count", _BRAVE_DEFAULT_RESULT_COUNT)
        if not isinstance(raw_count, int):
            raise ValueError("web_search field 'count' must be an integer")
        if raw_count <= 0 or raw_count > _BRAVE_MAX_RESULT_COUNT:
            raise ValueError(
                f"web_search field 'count' must be between 1 and {_BRAVE_MAX_RESULT_COUNT}"
            )

        raise UnconfiguredClientError(
            "web_search is not implemented in boxy-agent runtime; integrate via boxy-cloud"
        )

    def _call_python_exec(self, params: dict[str, JsonValue]) -> JsonValue:
        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("python_exec requires non-empty string field 'code'")

        raw_timeout = params.get("timeout_seconds", _PYTHON_DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(raw_timeout, (int, float)):
            raise ValueError("python_exec field 'timeout_seconds' must be a number")
        timeout_seconds = float(raw_timeout)
        if timeout_seconds <= 0 or timeout_seconds > _PYTHON_MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"python_exec field 'timeout_seconds' must be in (0, {_PYTHON_MAX_TIMEOUT_SECONDS}]"
            )

        result = self._python_executor.execute(code=code, timeout_seconds=timeout_seconds)
        limited_result = _limit_json_result(result.result, max_bytes=_PYTHON_MAX_RESULT_BYTES)
        return {
            "result": limited_result,
            "stdout": _truncate_text(result.stdout, max_chars=_PYTHON_MAX_STD_STREAM_CHARS),
            "stderr": _truncate_text(result.stderr, max_chars=_PYTHON_MAX_STD_STREAM_CHARS),
        }


def _call_monty_run(run: object, *, timeout_seconds: float) -> object:
    callable_run = cast(Callable[..., object], run)
    signature = inspect.signature(callable_run)
    kwargs: dict[str, object] = {}

    if "timeout_seconds" in signature.parameters:
        kwargs["timeout_seconds"] = timeout_seconds
    elif "timeout" in signature.parameters:
        kwargs["timeout"] = timeout_seconds

    return callable_run(**kwargs)


def _coerce_json_value(value: object) -> JsonValue | None:
    if value is None:
        return None
    if is_json_value(value):
        return cast(JsonValue, value)
    return repr(value)


def _coerce_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _truncate_text(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    suffix = f"\n...[truncated {len(value) - max_chars} chars]"
    keep = max(max_chars - len(suffix), 0)
    return f"{value[:keep]}{suffix}"


def _limit_json_result(value: JsonValue | None, *, max_bytes: int) -> JsonValue | None:
    if value is None:
        return None

    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    size = len(encoded.encode("utf-8"))
    if size <= max_bytes:
        return value

    preview = encoded[:_PYTHON_RESULT_PREVIEW_CHARS]
    return {
        "truncated": True,
        "size_bytes": size,
        "max_size_bytes": max_bytes,
        "preview": preview,
    }
