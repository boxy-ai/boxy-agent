from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from test_helpers.capabilities import empty_capability_catalog

from boxy_agent.compiler import package_agent
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.discovery import discover_registered_agents
from boxy_agent.runtime.errors import RegistrationError
from tests.support import write_agent_project


def _record(*, agent_id: str, agent_name: str, wheel_path: Path) -> dict[str, object]:
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "built_wheel": {"path": str(wheel_path)},
    }


def _package_runtime_agent(
    tmp_path: Path,
    *,
    distribution_name: str,
    package_name: str,
    agent_name: str,
) -> Path:
    project_dir = write_agent_project(
        project_dir=tmp_path / distribution_name,
        distribution_name=distribution_name,
        package_name=package_name,
        agent_name=agent_name,
        agent_source=(
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
            'version = "0.1.0"\n'
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
