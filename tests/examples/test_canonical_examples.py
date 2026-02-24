from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from test_helpers.capabilities import default_capability_catalog
from test_helpers.sdk_provider import MockAgentSdkProvider

from boxy_agent.compiler import package_agent
from boxy_agent.examples import (
    CANONICAL_AUTOMATION_EMAIL_AGENT_NAME,
    CANONICAL_DATA_MINING_EMAIL_AGENT_NAME,
    CANONICAL_MAIN_AGENT_NAME,
    canonical_automation_email_agent_project_dir,
    canonical_data_mining_email_agent_project_dir,
    canonical_main_agent_project_dir,
)
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.discovery import discover_registered_agents


def _require_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@contextmanager
def _example_sources_on_path(*project_dirs: Path) -> Iterator[None]:
    inserted: list[str] = []
    try:
        for project_dir in project_dirs:
            src_path = str((project_dir / "src").resolve())
            if src_path not in sys.path:
                sys.path.insert(0, src_path)
                inserted.append(src_path)
        yield
    finally:
        for src_path in inserted:
            while src_path in sys.path:
                sys.path.remove(src_path)


def _record(
    *,
    agent_name: str,
    packaged,
) -> dict[str, object]:
    return {
        "agent_id": agent_name,
        "agent_name": agent_name,
        "built_wheel": {"path": str(packaged.wheel_path)},
    }


def test_canonical_example_project_dirs_use_short_names() -> None:
    automation_dir = canonical_automation_email_agent_project_dir()
    data_mining_dir = canonical_data_mining_email_agent_project_dir()
    main_dir = canonical_main_agent_project_dir()

    assert automation_dir.name == "automation"
    assert data_mining_dir.name == "data_mining"
    assert main_dir.name == "main"

    assert (automation_dir / "pyproject.toml").exists()
    assert (data_mining_dir / "pyproject.toml").exists()
    assert (main_dir / "pyproject.toml").exists()
    assert not (automation_dir / "boxy_agent.toml").exists()
    assert not (data_mining_dir / "boxy_agent.toml").exists()
    assert not (main_dir / "boxy_agent.toml").exists()


def test_canonical_data_mining_agent_packaged_and_runs_end_to_end(tmp_path: Path) -> None:
    project_dir = canonical_data_mining_email_agent_project_dir()
    catalog = default_capability_catalog()
    packaged = package_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=catalog,
    )

    records = [
        _record(
            agent_name=CANONICAL_DATA_MINING_EMAIL_AGENT_NAME,
            packaged=packaged,
        )
    ]
    with _example_sources_on_path(project_dir):
        runtime = AgentRuntime(
            capability_catalog=catalog,
            sdk_provider=MockAgentSdkProvider(),
            agent_registry_loader=lambda: discover_registered_agents(records),
        )
        report = runtime.run(
            CANONICAL_DATA_MINING_EMAIL_AGENT_NAME,
            {"type": "scheduled.interval"},
        )

    assert report.status == "idle"
    output = _require_dict(report.last_output)
    assert output["status"] == "completed"
    assert output["message_count"] == 1
    queued_events = runtime.drain_event_queue()
    assert [item.event.type for item in queued_events] == ["insight.generated"]


def test_canonical_main_agent_observe_plan_act_paths_end_to_end(tmp_path: Path) -> None:
    automation_project_dir = canonical_automation_email_agent_project_dir()
    main_project_dir = canonical_main_agent_project_dir()
    catalog = default_capability_catalog()

    automation_packaged = package_agent(
        project_dir=automation_project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=catalog,
    )
    main_packaged = package_agent(
        project_dir=main_project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=catalog,
    )

    records = [
        _record(agent_name=CANONICAL_AUTOMATION_EMAIL_AGENT_NAME, packaged=automation_packaged),
        _record(agent_name=CANONICAL_MAIN_AGENT_NAME, packaged=main_packaged),
    ]
    with _example_sources_on_path(
        automation_project_dir,
        main_project_dir,
    ):
        runtime = AgentRuntime(
            capability_catalog=catalog,
            sdk_provider=MockAgentSdkProvider(),
            agent_registry_loader=lambda: discover_registered_agents(records),
        )
        delegated_report = runtime.run(
            CANONICAL_MAIN_AGENT_NAME,
            {"type": "start", "payload": {"mode": "delegate"}},
        )
        report_mode_report = runtime.run(
            CANONICAL_MAIN_AGENT_NAME,
            {"type": "start"},
        )
        ignored_report = runtime.run(CANONICAL_MAIN_AGENT_NAME, {"type": "email.reply_request"})

    assert delegated_report.status == "idle"
    assert report_mode_report.status == "idle"
    assert ignored_report.status == "idle"
    assert ignored_report.last_output is None

    delegated_output = _require_dict(delegated_report.last_output)
    assert delegated_output["phase"] == "complete"
    delegated_result = _require_dict(delegated_output["result"])
    assert delegated_result["mode"] == "delegate"
    delegated_payload = _require_dict(delegated_result["delegated_output"])
    assert delegated_payload["status"] == "completed"

    report_mode_output = _require_dict(report_mode_report.last_output)
    assert report_mode_output["phase"] == "complete"
    report_mode_result = _require_dict(report_mode_output["result"])
    assert report_mode_result["mode"] == "report"
    assert report_mode_result["message_count"] == 1
