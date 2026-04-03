from __future__ import annotations

import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest
from support import write_agent_project
from test_helpers.capabilities import default_capability_catalog

from boxy_agent.compiler import package_agent
from boxy_agent.compiler.package import PackagingError, _build_wheel


def _make_project(tmp_path: Path) -> Path:
    source = (
        "from boxy_agent.sdk import decorators, models\n"
        "\n"
        "@decorators.agent_main\n"
        "def handle(context):\n"
        '    return models.AgentResult(output={"event": context.event.type})\n'
    )
    metadata = """
[tool.boxy_agent.agent]
name = "test-agent"
description = "Packaged test agent"
version = "1.2.3"
type = "automation"
module = "sample_agent.agent"
expected_event_types = ["start"]

[tool.boxy_agent.capabilities]
data_queries = ["whatsapp.chat_context"]
boxy_tools = []
builtin_tools = []
event_emitters = []
""".strip()

    project_dir = tmp_path / "project"
    return write_agent_project(
        project_dir=project_dir,
        distribution_name="sample-agent-wheel",
        package_name="sample_agent",
        agent_name="test-agent",
        agent_source=source,
        metadata_toml=metadata,
    )


def test_package_agent_builds_wheel_with_manifest(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    output_dir = tmp_path / "dist"

    packaged = package_agent(
        project_dir=project_dir,
        output_dir=output_dir,
        capability_catalog=default_capability_catalog(),
    )

    assert packaged.wheel_path.exists()
    assert packaged.wheel_path.suffix == ".whl"
    assert packaged.manifest_module == "sample_agent.boxy_agent_compiled_manifest"

    with zipfile.ZipFile(packaged.wheel_path) as wheel:
        names = set(wheel.namelist())
        manifest_module_path = "sample_agent/boxy_agent_compiled_manifest.py"
        assert manifest_module_path in names
        manifest_module_contents = wheel.read(manifest_module_path).decode("utf-8")
        assert "COMPILED_AGENT_MANIFEST" in manifest_module_contents
        assert "json.loads" in manifest_module_contents


def test_package_agent_preserves_existing_pyproject_entry_points(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    pyproject_path = project_dir / "pyproject.toml"
    original_pyproject = pyproject_path.read_text(encoding="utf-8")
    expected_pyproject = (
        original_pyproject
        + '\n[project.entry-points."console_scripts"]\n'
        + 'existing = "sample_agent.agent:handle"\n'
    )
    pyproject_path.write_text(expected_pyproject, encoding="utf-8")

    package_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "dist",
        capability_catalog=default_capability_catalog(),
    )

    assert pyproject_path.read_text(encoding="utf-8") == expected_pyproject


def test_package_agent_can_rebuild_same_version_in_same_output_dir(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    output_dir = tmp_path / "dist"

    first = package_agent(
        project_dir=project_dir,
        output_dir=output_dir,
        capability_catalog=default_capability_catalog(),
    )
    second = package_agent(
        project_dir=project_dir,
        output_dir=output_dir,
        capability_catalog=default_capability_catalog(),
    )

    assert first.wheel_path.exists()
    assert second.wheel_path.exists()
    assert first.wheel_path.name == second.wheel_path.name


def test_build_wheel_uses_non_isolated_mode(monkeypatch, tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    output_dir = tmp_path / "dist"
    stage_dir.mkdir()
    output_dir.mkdir()
    observed_command: list[str] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        text: bool,
        capture_output: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        observed_command.extend(command)
        assert cwd == stage_dir
        assert text is True
        assert capture_output is True
        assert check is False
        outdir = Path(command[command.index("--outdir") + 1])
        (outdir / "sample-0.1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("boxy_agent.compiler.package.subprocess.run", fake_run)

    wheel_path = _build_wheel(stage_dir=stage_dir, output_dir=output_dir)

    assert "--no-isolation" in observed_command
    assert wheel_path == output_dir / "sample-0.1.0-py3-none-any.whl"
    assert wheel_path.exists()


def test_build_wheel_requires_packaging_dependencies(monkeypatch, tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    output_dir = tmp_path / "dist"
    stage_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr("boxy_agent.compiler.package.importlib.util.find_spec", lambda _name: None)

    with pytest.raises(PackagingError, match="packaging' extra"):
        _build_wheel(stage_dir=stage_dir, output_dir=output_dir)


def test_project_config_includes_example_pyproject_package_data() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = pyproject["tool"]["setuptools"]["package-data"]["boxy_agent"]
    assert "builtin_capability.json" in patterns
    assert "capability_catalog.json" in patterns
