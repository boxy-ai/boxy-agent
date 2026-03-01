from __future__ import annotations

import boxy_agent
import boxy_agent.compiler as compiler
import boxy_agent.runtime as runtime
import boxy_agent.sdk as sdk


def _assert_export_surface(*, module_name: str, expected: set[str], exported: list[str]) -> None:
    missing = expected.difference(exported)
    assert not missing, f"{module_name} missing exports: {sorted(missing)}"


def test_public_api_export_surfaces() -> None:
    _assert_export_surface(
        module_name="boxy_agent.runtime",
        exported=runtime.__all__,
        expected={
            "AgentSdkProvider",
            "AgentRuntime",
            "CapabilitySchemaError",
            "CapabilityViolationError",
            "CoreAgentSdkProvider",
            "EventQueueItem",
            "InstalledAgent",
            "RunReport",
            "TraceRecord",
        },
    )
    _assert_export_surface(
        module_name="boxy_agent.compiler",
        exported=compiler.__all__,
        expected={
            "CompiledAgent",
            "CompiledManifest",
            "PackagedAgent",
            "compile_agent",
            "package_agent",
        },
    )
    _assert_export_surface(
        module_name="boxy_agent",
        exported=boxy_agent.__all__,
        expected={
            "AgentExecutionContext",
            "AgentRuntime",
            "agent_main",
            "compile_agent",
            "package_agent",
            "sdk",
            "query_data",
            "call_boxy_tool",
            "call_builtin_tool",
            "emit_event",
        },
    )
    _assert_export_surface(
        module_name="boxy_agent.sdk",
        exported=sdk.__all__,
        expected={
            "models",
            "decorators",
            "interfaces",
            "events",
            "llm",
            "data_queries",
            "boxy_tools",
            "builtin_tools",
            "memory",
            "tracing",
            "control",
        },
    )
