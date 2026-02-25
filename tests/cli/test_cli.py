from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from boxy_agent.cli import main
from boxy_agent.models import AgentCapabilities
from boxy_agent.runtime.models import InstalledAgent, RunReport, TraceRecord


def _write_empty_catalog(path: Path) -> Path:
    path.write_text(
        """
schema_version = 1
data_queries = []
boxy_tools = []
builtin_tools = []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


def test_cli_compile_command(monkeypatch, capsys, tmp_path: Path) -> None:
    called: dict[str, object] = {}
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")

    def fake_compile_agent(
        *,
        project_dir: Path,
        output_dir: Path,
        capability_catalog,
    ):
        called["project_dir"] = project_dir
        called["output_dir"] = output_dir
        called["catalog"] = capability_catalog
        return SimpleNamespace(manifest_path=output_dir / "manifest.json")

    monkeypatch.setattr("boxy_agent.cli.compile_agent", fake_compile_agent)

    exit_code = main(
        [
            "compile",
            "--project-dir",
            str(tmp_path / "project"),
            "--output-dir",
            str(tmp_path / "dist"),
            "--capability-catalog",
            str(catalog_path),
        ]
    )

    assert exit_code == 0
    assert called["project_dir"] == (tmp_path / "project")
    assert called["output_dir"] == (tmp_path / "dist")
    assert called["catalog"] is not None
    assert "manifest.json" in capsys.readouterr().out


def test_cli_package_command(monkeypatch, capsys, tmp_path: Path) -> None:
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")

    def fake_package_agent(
        *,
        project_dir: Path,
        output_dir: Path,
        capability_catalog,
    ):
        return SimpleNamespace(wheel_path=output_dir / "sample.whl")

    monkeypatch.setattr("boxy_agent.cli.package_agent", fake_package_agent)

    exit_code = main(
        [
            "package",
            "--project-dir",
            str(tmp_path / "project"),
            "--output-dir",
            str(tmp_path / "dist"),
            "--capability-catalog",
            str(catalog_path),
        ]
    )

    assert exit_code == 0
    assert "sample.whl" in capsys.readouterr().out


def test_cli_list_agents_json(monkeypatch, capsys, tmp_path: Path) -> None:
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")

    class FakeRuntime:
        def __init__(self, *, capability_catalog=None) -> None:
            self._catalog = capability_catalog

        def list_installed_agents(self) -> list[InstalledAgent]:
            return [
                InstalledAgent(
                    name="agent-a",
                    description="Agent A",
                    version="1.0.0",
                    agent_type="automation",
                    expected_event_types=("start",),
                    capabilities=AgentCapabilities(
                        data_queries=frozenset({"gmail.messages"}),
                        boxy_tools=frozenset(),
                        builtin_tools=frozenset(),
                    ),
                )
            ]

    monkeypatch.setattr("boxy_agent.cli.AgentRuntime", FakeRuntime)

    exit_code = main(
        [
            "list-agents",
            "--json",
            "--capability-catalog",
            str(catalog_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["name"] == "agent-a"
    assert payload[0]["capabilities"]["event_emitters"] == []


def test_cli_run_with_event_inputs(monkeypatch, capsys, tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text('{"type": "start", "payload": {"a": 1}}', encoding="utf-8")
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")
    run_calls: list[dict[str, object]] = []

    class FakeRuntime:
        def __init__(self, *, capability_catalog=None) -> None:
            self._catalog = capability_catalog

        def run(self, agent_name: str, event: dict[str, object]):
            assert agent_name == "agent-a"
            run_calls.append(event)
            return RunReport(
                session_id="s1",
                status="idle",
                last_output={"ok": True},
                traces=[
                    TraceRecord(
                        session_id="s1",
                        agent_name="agent-a",
                        event_type="start",
                        expected_event_types=("start",),
                        matched_expected_event_type=True,
                        trace_name="step.start",
                        payload={},
                    )
                ],
            )

    monkeypatch.setattr("boxy_agent.cli.AgentRuntime", FakeRuntime)

    exit_code = main(
        [
            "run",
            "--agent",
            "agent-a",
            "--capability-catalog",
            str(catalog_path),
            "--event-json",
            '{"type": "start"}',
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "idle"
    assert payload["last_output"] == {"ok": True}
    assert run_calls[-1] == {"type": "start", "description": "", "payload": {}}

    exit_code = main(
        [
            "run",
            "--agent",
            "agent-a",
            "--capability-catalog",
            str(catalog_path),
            "--event-file",
            str(event_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["last_output"] == {"ok": True}
    assert run_calls[-1] == {"type": "start", "description": "", "payload": {"a": 1}}


def test_cli_run_with_registry_file_loads_registry_records(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "registry.json"
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")
    registry_records = [
        {
            "agent_id": "agent-a",
            "agent_name": "agent-a",
            "built_wheel": {"path": "/tmp/agent-a.whl"},
        }
    ]
    registry_path.write_text(json.dumps(registry_records), encoding="utf-8")

    called: dict[str, object] = {}

    def fake_discover_registered_agents(records):
        called["records"] = records
        return {}

    class FakeRuntime:
        def __init__(self, *, capability_catalog=None, agent_registry_loader=None) -> None:
            self._catalog = capability_catalog
            self._loader = agent_registry_loader

        def run(self, agent_name: str, event: dict[str, object]):
            called["agent_name"] = agent_name
            called["event_type"] = event["type"]
            if self._loader is not None:
                self._loader()
            return RunReport(
                session_id="s1",
                status="idle",
                last_output={"ok": True},
                traces=[],
            )

    monkeypatch.setattr(
        "boxy_agent.cli.discover_registered_agents",
        fake_discover_registered_agents,
    )
    monkeypatch.setattr("boxy_agent.cli.AgentRuntime", FakeRuntime)

    exit_code = main(
        [
            "run",
            "--agent",
            "agent-a",
            "--registry-file",
            str(registry_path),
            "--capability-catalog",
            str(catalog_path),
            "--event-json",
            '{"type": "start"}',
        ]
    )

    assert exit_code == 0
    assert called["records"] == registry_records
    assert called["agent_name"] == "agent-a"
    assert called["event_type"] == "start"
    payload = json.loads(capsys.readouterr().out)
    assert payload["last_output"] == {"ok": True}


def test_cli_run_closes_runtime_resources_when_event_parsing_fails(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    catalog_path = _write_empty_catalog(tmp_path / "catalog.toml")
    called: dict[str, object] = {"closed": False}

    class FakeRuntime:
        def run(self, agent_name: str, event: dict[str, object]):  # pragma: no cover
            _ = agent_name, event
            raise AssertionError("run should not be called when event parsing fails")

    def fake_runtime_from_args(args, *, capability_catalog):
        _ = args, capability_catalog

        def close() -> None:
            called["closed"] = True

        return FakeRuntime(), close

    monkeypatch.setattr("boxy_agent.cli._runtime_from_args", fake_runtime_from_args)

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "run",
                "--agent",
                "agent-a",
                "--capability-catalog",
                str(catalog_path),
                "--event-json",
                "{",
            ]
        )

    assert exc.value.code == 1
    assert called["closed"] is True
    assert "error:" in capsys.readouterr().err


def test_cli_compile_with_capability_catalog(monkeypatch, tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.toml"
    catalog_path.write_text("schema_version = 1\n", encoding="utf-8")

    called: dict[str, object] = {}

    def fake_load_capability_catalog(path: Path):
        called["catalog_path"] = path
        return "loaded-catalog"

    def fake_compile_agent(*, project_dir: Path, output_dir: Path, capability_catalog):
        called["capability_catalog"] = capability_catalog
        return SimpleNamespace(manifest_path=output_dir / "manifest.json")

    monkeypatch.setattr("boxy_agent.cli.load_capability_catalog", fake_load_capability_catalog)
    monkeypatch.setattr("boxy_agent.cli.compile_agent", fake_compile_agent)

    exit_code = main(
        [
            "compile",
            "--project-dir",
            str(tmp_path / "project"),
            "--output-dir",
            str(tmp_path / "dist"),
            "--capability-catalog",
            str(catalog_path),
        ]
    )

    assert exit_code == 0
    assert called["catalog_path"] == catalog_path
    assert called["capability_catalog"] == "loaded-catalog"


def test_cli_create_agent_generates_operation_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "email-ops-agent"

    exit_code = main(
        [
            "create-agent",
            "operation",
            "--project-dir",
            str(project_dir),
        ]
    )

    assert exit_code == 0
    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    agent_table = pyproject["tool"]["boxy_agent"]["agent"]
    capabilities_table = pyproject["tool"]["boxy_agent"]["capabilities"]

    assert pyproject["project"]["name"] == "email-ops-agent"
    assert agent_table["type"] == "automation"
    assert agent_table["module"] == "email_ops_agent.agent"
    assert agent_table["expected_event_types"] == ["start"]
    assert capabilities_table["data_queries"] == []
    assert capabilities_table["boxy_tools"] == []
    assert capabilities_table["builtin_tools"] == []
    assert capabilities_table["event_emitters"] == []

    assert (project_dir / "src" / "email_ops_agent" / "__init__.py").exists()
    assert (project_dir / "src" / "email_ops_agent" / "agent.py").exists()


def test_cli_create_agent_generates_data_mining_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "data-agent"

    exit_code = main(
        [
            "create-agent",
            "data-mining",
            "--project-dir",
            str(project_dir),
            "--name",
            "custom-data-agent",
        ]
    )

    assert exit_code == 0
    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    agent_table = pyproject["tool"]["boxy_agent"]["agent"]

    assert pyproject["project"]["name"] == "custom-data-agent"
    assert agent_table["type"] == "data_mining"
    assert agent_table["module"] == "custom_data_agent.agent"
    assert "expected_event_types" not in agent_table


def test_cli_create_agent_escapes_description_quotes(tmp_path: Path) -> None:
    project_dir = tmp_path / "quoted-description-agent"
    description = 'Say "hello"'

    exit_code = main(
        [
            "create-agent",
            "operation",
            "--project-dir",
            str(project_dir),
            "--description",
            description,
        ]
    )

    assert exit_code == 0
    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["description"] == description
    assert pyproject["tool"]["boxy_agent"]["agent"]["description"] == description


def test_cli_create_agent_rejects_main_without_internal(capsys, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "create-agent",
                "main",
                "--project-dir",
                str(tmp_path / "main-agent"),
            ]
        )

    assert exc.value.code == 1
    assert "internal-only" in capsys.readouterr().err


def test_cli_create_agent_rejects_unsupported_type(capsys, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "create-agent",
                "automation",
                "--project-dir",
                str(tmp_path / "automation-agent"),
            ]
        )

    assert exc.value.code == 1
    assert "Supported types: data-mining, operation" in capsys.readouterr().err


def test_cli_create_agent_allows_main_with_internal(tmp_path: Path) -> None:
    project_dir = tmp_path / "main-agent"

    exit_code = main(
        [
            "create-agent",
            "main",
            "--project-dir",
            str(project_dir),
            "--internal",
        ]
    )

    assert exit_code == 0
    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    agent_table = pyproject["tool"]["boxy_agent"]["agent"]
    assert agent_table["type"] == "main"
    assert agent_table["expected_event_types"] == ["start"]
