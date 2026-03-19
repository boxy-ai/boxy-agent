from __future__ import annotations

from pathlib import Path
from typing import cast

from test_helpers.capabilities import default_capability_catalog
from test_helpers.sdk_provider import MockAgentSdkProvider

from boxy_agent.compiler import package_agent
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.discovery import discover_registered_agents

REFERENCE_AUTOMATION_AGENT_NAME = "reference-automation-chat-agent"
REFERENCE_DATA_MINING_AGENT_NAME = "reference-data-mining-chat-agent"


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _example_project_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "examples" / name


def _record(*, agent_name: str, packaged) -> dict[str, object]:
    return {
        "agent_id": agent_name,
        "agent_name": agent_name,
        "built_wheel": {"path": str(packaged.wheel_path)},
    }


def test_reference_example_project_dirs_use_repo_examples() -> None:
    automation_dir = _example_project_dir("automation")
    data_mining_dir = _example_project_dir("data_mining")

    assert automation_dir.name == "automation"
    assert data_mining_dir.name == "data_mining"

    assert (automation_dir / "pyproject.toml").exists()
    assert (data_mining_dir / "pyproject.toml").exists()
    assert not (automation_dir / "boxy_agent.toml").exists()
    assert not (data_mining_dir / "boxy_agent.toml").exists()


def test_reference_data_mining_agent_packaged_and_runs_end_to_end(tmp_path: Path) -> None:
    project_dir = _example_project_dir("data_mining")
    catalog = default_capability_catalog()
    packaged = package_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=catalog,
    )

    runtime = AgentRuntime(
        capability_catalog=catalog,
        sdk_provider=MockAgentSdkProvider(),
        agent_registry_loader=lambda: discover_registered_agents(
            [_record(agent_name=REFERENCE_DATA_MINING_AGENT_NAME, packaged=packaged)]
        ),
    )
    report = runtime.run(
        REFERENCE_DATA_MINING_AGENT_NAME,
        {"type": "scheduled.interval", "payload": {"chat_jid": "chat-1"}},
    )

    assert report.status == "idle"
    output = _require_dict(report.last_output)
    assert output["status"] == "completed"
    assert output["message_count"] == 1
    queued_events = runtime.drain_event_queue()
    assert [item.event.type for item in queued_events] == ["insight.generated"]


def test_reference_automation_agent_packaged_and_runs_end_to_end(tmp_path: Path) -> None:
    project_dir = _example_project_dir("automation")
    catalog = default_capability_catalog()
    packaged = package_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=catalog,
    )

    runtime = AgentRuntime(
        capability_catalog=catalog,
        sdk_provider=MockAgentSdkProvider(),
        agent_registry_loader=lambda: discover_registered_agents(
            [_record(agent_name=REFERENCE_AUTOMATION_AGENT_NAME, packaged=packaged)]
        ),
    )
    report = runtime.run(
        REFERENCE_AUTOMATION_AGENT_NAME,
        {
            "type": "chat.reply_request",
            "payload": {"target": "chat-1", "chat_jid": "chat-1"},
        },
    )

    assert report.status == "idle"
    output = _require_dict(report.last_output)
    assert output["status"] == "completed"
    assert output["target"] == "chat-1"
    assert output["message_count"] == 1
