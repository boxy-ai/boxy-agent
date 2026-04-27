from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from test_helpers.capabilities import empty_capability_catalog

from boxy_agent._version import __version__ as BOXY_AGENT_VERSION
from boxy_agent.compiler import package_agent
from boxy_agent.compiler.models import MANIFEST_SCHEMA_VERSION
from boxy_agent.execution_affinity import ExecutionAffinity
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.discovery import discover_registered_agents, validate_wheel_entrypoint
from boxy_agent.runtime.errors import RegistrationError
from boxy_agent.runtime.wheel_inspection import inspect_wheel_artifact
from boxy_agent.sdk import models
from boxy_agent.types import JsonValue
from tests.support import write_agent_project


def _record(*, agent_id: str, agent_name: str, wheel_path: Path) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "built_wheel": {"path": str(wheel_path)},
    }


class _NoopBindings:
    def llm_chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        raise AssertionError("registry discovery handler should not call llm runtime bindings")

    def llm_chat_complete_stream(
        self, request: dict[str, JsonValue], on_partial
    ) -> dict[str, JsonValue]:
        _ = on_partial
        raise AssertionError("registry discovery handler should not call llm runtime bindings")

    def list_data_queries(self) -> list[models.DataQueryDescriptor]:
        return []

    def data_query_execution_affinities(self) -> dict[str, ExecutionAffinity]:
        return {}

    def query_data(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError(f"registry discovery handler should not query data: {name}")

    def list_boxy_tools(self) -> list[models.ToolDescriptor]:
        return []

    def boxy_tool_execution_affinities(self) -> dict[str, ExecutionAffinity]:
        return {}

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError(f"registry discovery handler should not call boxy tool: {name}")

    def list_builtin_tools(self) -> list[models.ToolDescriptor]:
        return []

    def builtin_tool_execution_affinities(self) -> dict[str, ExecutionAffinity]:
        return {}

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        raise AssertionError(f"registry discovery handler should not call built-in tool: {name}")

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        return None

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        raise AssertionError(f"registry discovery handler should not write memory: {key}")

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        raise AssertionError(f"registry discovery handler should not delete memory: {key}")

    def trace(self, name: str, payload: dict[str, JsonValue] | None = None) -> None:
        raise AssertionError(f"registry discovery handler should not emit traces: {name}")

    def terminate(self, reason: str | None = None) -> None:
        raise AssertionError(f"registry discovery handler should not terminate: {reason}")

    def emit_event(self, event: models.AgentEvent) -> None:
        raise AssertionError(
            f"registry discovery handler should not emit runtime events: {event.type}"
        )


def _execution_context() -> models.AgentExecutionContext:
    return models.AgentExecutionContext(
        event=models.AgentEvent(type="start", description="Start", payload={}),
        session_id="session-1",
        agent_name="main",
        _runtime=_NoopBindings(),
    )


def _package_runtime_agent(
    tmp_path: Path,
    *,
    distribution_name: str,
    package_name: str,
    agent_name: str,
    version: str = "0.1.0",
    agent_source: str | None = None,
) -> Path:
    project_dir = write_agent_project(
        project_dir=tmp_path / distribution_name,
        distribution_name=distribution_name,
        package_name=package_name,
        agent_name=agent_name,
        agent_source=agent_source
        or (
            "from boxy_agent.sdk import decorators, models\n"
            "\n"
            "@decorators.agent_main\n"
            "def handle(context):\n"
            '    return models.AgentResult(output={"event_type": context.event.type})\n'
        ),
        metadata_toml=(
            "[tool.boxy_agent.agent]\n"
            f'name = "{agent_name}"\n'
            f'description = "{agent_name} agent"\n'
            f'version = "{version}"\n'
            'type = "automation"\n'
            f'module = "{package_name}.agent"\n'
            'expected_event_types = ["start"]\n'
            "\n"
            "[tool.boxy_agent.capabilities]\n"
            "data_queries = []\n"
            "boxy_tools = []\n"
            "builtin_tools = []\n"
            "event_emitters = []\n"
        ),
    )
    packaged = package_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=empty_capability_catalog(),
    )
    return packaged.wheel_path


def _wheel_without_manifest(tmp_path: Path) -> Path:
    wheel_path = tmp_path / "broken-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as wheel:
        wheel.writestr("broken_agent/__init__.py", "")
        wheel.writestr("broken_agent/agent.py", "VALUE = 1\n")
    return wheel_path


def _wheel_with_invalid_manifest_payload(tmp_path: Path) -> Path:
    wheel_path = tmp_path / "invalid-manifest-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as wheel:
        wheel.writestr("invalid_manifest/__init__.py", "")
        wheel.writestr(
            "invalid_manifest/boxy_agent_compiled_manifest.py",
            "COMPILED_AGENT_MANIFEST = json.loads('{\"name\": }')\n",
        )
    return wheel_path


def _wheel_with_noncallable_entrypoint(tmp_path: Path) -> Path:
    wheel_path = tmp_path / "invalid-entrypoint-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as wheel:
        wheel.writestr("invalid_entrypoint/__init__.py", "")
        wheel.writestr("invalid_entrypoint/agent.py", "handle = 1\n")
        wheel.writestr(
            "invalid_entrypoint/boxy_agent_compiled_manifest.py",
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "COMPILED_AGENT_MANIFEST = {",
                    f'    "schema_version": {MANIFEST_SCHEMA_VERSION},',
                    '    "name": "main",',
                    '    "description": "main agent",',
                    '    "version": "0.1.0",',
                    '    "type": "automation",',
                    '    "requires": {',
                    f'        "boxy-agent": ">={BOXY_AGENT_VERSION},<0.3.0",',
                    "    },",
                    '    "built_with": {',
                    f'        "boxy-agent": "{BOXY_AGENT_VERSION}",',
                    "    },",
                    '    "entrypoint": {',
                    '        "module": "invalid_entrypoint.agent",',
                    '        "function": "handle",',
                    "    },",
                    '    "expected_event_types": ["start"],',
                    '    "capabilities": {',
                    '        "data_queries": [],',
                    '        "boxy_tools": [],',
                    '        "builtin_tools": [],',
                    '        "event_emitters": [],',
                    "    },",
                    "}",
                    "",
                ]
            ),
        )
    return wheel_path


def _wheel_requiring_incompatible_sdk(tmp_path: Path) -> Path:
    wheel_path = tmp_path / "incompatible-sdk-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as wheel:
        wheel.writestr("incompatible_sdk/__init__.py", "")
        wheel.writestr("incompatible_sdk/agent.py", "def handle(_context):\n    return None\n")
        wheel.writestr(
            "incompatible_sdk/boxy_agent_compiled_manifest.py",
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "COMPILED_AGENT_MANIFEST = {",
                    f'    "schema_version": {MANIFEST_SCHEMA_VERSION},',
                    '    "name": "incompatible-sdk",',
                    '    "description": "incompatible agent",',
                    '    "version": "0.1.0",',
                    '    "type": "automation",',
                    '    "requires": {',
                    '        "boxy-agent": ">=0.3.0,<0.4.0",',
                    "    },",
                    '    "built_with": {',
                    f'        "boxy-agent": "{BOXY_AGENT_VERSION}",',
                    "    },",
                    '    "entrypoint": {',
                    '        "module": "incompatible_sdk.agent",',
                    '        "function": "handle",',
                    "    },",
                    '    "expected_event_types": ["start"],',
                    '    "capabilities": {',
                    '        "data_queries": [],',
                    '        "boxy_tools": [],',
                    '        "builtin_tools": [],',
                    '        "event_emitters": [],',
                    "    },",
                    "}",
                    "",
                ]
            ),
        )
    return wheel_path


def _wheel_with_schema_one_manifest(tmp_path: Path) -> Path:
    wheel_path = tmp_path / "schema-one-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as wheel:
        wheel.writestr("schema_one/__init__.py", "")
        wheel.writestr("schema_one/agent.py", "def handle(_context):\n    return None\n")
        wheel.writestr(
            "schema_one/boxy_agent_compiled_manifest.py",
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "COMPILED_AGENT_MANIFEST = {",
                    '    "schema_version": 1,',
                    '    "name": "schema-one",',
                    '    "description": "old schema agent",',
                    '    "version": "0.1.0",',
                    '    "type": "automation",',
                    '    "entrypoint": {',
                    '        "module": "schema_one.agent",',
                    '        "function": "handle",',
                    "    },",
                    '    "expected_event_types": ["start"],',
                    '    "capabilities": {',
                    '        "data_queries": [],',
                    '        "boxy_tools": [],',
                    '        "builtin_tools": [],',
                    '        "event_emitters": [],',
                    "    },",
                    "}",
                    "",
                ]
            ),
        )
    return wheel_path


def test_inspect_wheel_artifact_reads_manifest_without_importing_modules(tmp_path: Path) -> None:
    wheel_path = _package_runtime_agent(
        tmp_path,
        distribution_name="inspect-main-agent",
        package_name="inspect_main_agent",
        agent_name="main",
    )

    inspected = inspect_wheel_artifact(wheel_path=wheel_path)

    assert inspected.wheel_path == wheel_path
    assert inspected.manifest_module_name == "inspect_main_agent.boxy_agent_compiled_manifest"
    assert inspected.installed.name == "main"
    assert inspected.installed.version == "0.1.0"


def test_discover_registered_agents_loads_manifest_and_handler_from_wheel(tmp_path: Path) -> None:
    wheel_path = _package_runtime_agent(
        tmp_path,
        distribution_name="registry-main-agent",
        package_name="registry_main_agent",
        agent_name="main",
    )

    discovered = discover_registered_agents(
        [_record(agent_id="agent-main", agent_name="main", wheel_path=wheel_path)]
    )

    assert list(discovered) == ["main"]
    assert discovered["main"].installed.name == "main"
    assert discovered["main"].installed.version == "0.1.0"
    assert callable(discovered["main"].handler)


def test_discover_registered_agents_rejects_duplicate_registry_rows(tmp_path: Path) -> None:
    wheel_a = _package_runtime_agent(
        tmp_path,
        distribution_name="registry-main-a",
        package_name="registry_main_a",
        agent_name="main",
    )
    wheel_b = _package_runtime_agent(
        tmp_path,
        distribution_name="registry-main-b",
        package_name="registry_main_b",
        agent_name="main",
    )

    with pytest.raises(RegistrationError, match="Duplicate agent_name"):
        discover_registered_agents(
            [
                _record(agent_id="agent-main-1", agent_name="main", wheel_path=wheel_a),
                _record(agent_id="agent-main-2", agent_name="main", wheel_path=wheel_b),
            ]
        )


def test_discover_registered_agents_requires_wheel_path() -> None:
    with pytest.raises(RegistrationError, match="built_wheel.path"):
        discover_registered_agents(
            [
                {
                    "agent_id": "agent-main",
                    "agent_name": "main",
                    "built_wheel": {},
                }
            ]
        )


def test_discover_registered_agents_rejects_missing_wheel_file() -> None:
    with pytest.raises(RegistrationError, match="does not exist"):
        discover_registered_agents(
            [
                _record(
                    agent_id="agent-main",
                    agent_name="main",
                    wheel_path=Path("/tmp/not-found.whl"),
                )
            ]
        )


def test_discover_registered_agents_rejects_wheel_without_embedded_manifest(tmp_path: Path) -> None:
    with pytest.raises(RegistrationError, match="missing embedded compiled manifest"):
        discover_registered_agents(
            [
                _record(
                    agent_id="agent-main",
                    agent_name="main",
                    wheel_path=_wheel_without_manifest(tmp_path),
                )
            ]
        )


def test_inspect_wheel_artifact_rejects_invalid_manifest_payload(tmp_path: Path) -> None:
    with pytest.raises(RegistrationError, match="Compiled manifest JSON is invalid"):
        inspect_wheel_artifact(
            wheel_path=_wheel_with_invalid_manifest_payload(tmp_path),
            agent_name="main",
        )


def test_inspect_wheel_artifact_rejects_schema_one_manifest(tmp_path: Path) -> None:
    with pytest.raises(RegistrationError, match="Unsupported manifest schema_version"):
        inspect_wheel_artifact(
            wheel_path=_wheel_with_schema_one_manifest(tmp_path),
            agent_name="schema-one",
        )


def test_inspect_wheel_artifact_rejects_incompatible_sdk_requirement(tmp_path: Path) -> None:
    with pytest.raises(RegistrationError, match="does not satisfy"):
        inspect_wheel_artifact(
            wheel_path=_wheel_requiring_incompatible_sdk(tmp_path),
            agent_name="incompatible-sdk",
        )


def test_validate_wheel_entrypoint_rejects_noncallable_handler(tmp_path: Path) -> None:
    with pytest.raises(RegistrationError, match="is not callable"):
        validate_wheel_entrypoint(
            wheel_path=_wheel_with_noncallable_entrypoint(tmp_path),
            agent_name="main",
        )


def test_runtime_can_execute_agent_loaded_directly_from_wheel_artifact(tmp_path: Path) -> None:
    wheel_path = _package_runtime_agent(
        tmp_path,
        distribution_name="runtime-main-agent",
        package_name="runtime_main_agent",
        agent_name="main",
    )
    records = [_record(agent_id="agent-main", agent_name="main", wheel_path=wheel_path)]
    runtime = AgentRuntime(
        capability_catalog=empty_capability_catalog(),
        agent_registry_loader=lambda: discover_registered_agents(records),
    )

    report = runtime.run("main", {"type": "start"})

    assert report.status == "idle"
    assert report.last_output == {"event_type": "start"}


def test_discover_registered_agents_reloads_wheel_modules_after_upgrade(tmp_path: Path) -> None:
    wheel_v1 = _package_runtime_agent(
        tmp_path,
        distribution_name="runtime-upgrade-agent-v1",
        package_name="runtime_upgrade_agent",
        agent_name="main",
        version="0.1.0",
        agent_source=(
            "from boxy_agent.sdk import decorators, models\n"
            "\n"
            "@decorators.agent_main\n"
            "def handle(_context):\n"
            '    return models.AgentResult(output={"version": "0.1.0"})\n'
        ),
    )
    first = discover_registered_agents(
        [_record(agent_id="agent-main", agent_name="main", wheel_path=wheel_v1)]
    )
    first_result = first["main"].handler(_execution_context())
    assert isinstance(first_result, models.AgentResult)
    assert first_result.output == {"version": "0.1.0"}

    wheel_v2 = _package_runtime_agent(
        tmp_path,
        distribution_name="runtime-upgrade-agent-v2",
        package_name="runtime_upgrade_agent",
        agent_name="main",
        version="0.2.0",
        agent_source=(
            "from boxy_agent.sdk import decorators, models\n"
            "\n"
            "@decorators.agent_main\n"
            "def handle(_context):\n"
            '    return models.AgentResult(output={"version": "0.2.0"})\n'
        ),
    )
    second = discover_registered_agents(
        [_record(agent_id="agent-main", agent_name="main", wheel_path=wheel_v2)]
    )

    assert second["main"].installed.version == "0.2.0"
    second_result = second["main"].handler(_execution_context())
    assert isinstance(second_result, models.AgentResult)
    assert second_result.output == {"version": "0.2.0"}
