from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import cast

from support import write_agent_project

from boxy_agent.compiler import package_agent


def test_package_run_in_clean_venv_without_repo_path_hacks(tmp_path: Path) -> None:
    project_dir = write_agent_project(
        project_dir=tmp_path / "agent-project",
        distribution_name="sample-agent-e2e",
        package_name="sample_agent_e2e",
        agent_name="sample-agent-e2e",
        agent_source=(
            "from boxy_agent.sdk import decorators, models\n"
            "\n"
            "@decorators.agent_main\n"
            "def handle(context):\n"
            '    return models.AgentResult(output={"event_type": context.event.type})\n'
        ),
        metadata_toml=(
            "[tool.boxy_agent.agent]\n"
            'name = "sample-agent-e2e"\n'
            'description = "E2E agent"\n'
            'version = "0.0.1"\n'
            'type = "automation"\n'
            'module = "sample_agent_e2e.agent"\n'
            'expected_event_types = ["start"]\n'
            "\n"
            "[tool.boxy_agent.capabilities]\n"
            "data_queries = []\n"
            "boxy_tools = []\n"
            "builtin_tools = []\n"
            "event_emitters = []\n"
        ),
    )

    dist_dir = tmp_path / "dist"
    packaged = package_agent(
        project_dir=project_dir,
        output_dir=dist_dir,
    )

    sdk_wheel = _build_sdk_wheel(tmp_path / "sdk-dist")
    with zipfile.ZipFile(sdk_wheel) as wheel:
        assert "boxy_agent/_catalog_generation.py" not in wheel.namelist()
    venv_dir = tmp_path / "venv"
    _run([sys.executable, "-m", "venv", str(venv_dir)])
    python_bin = venv_dir / "bin" / "python"

    _run([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(python_bin), "-m", "pip", "install", str(sdk_wheel)])

    catalog_probe = _run_json(
        [
            str(python_bin),
            "-c",
            (
                "from boxy_agent.capabilities import load_packaged_capability_catalog; "
                "catalog = load_packaged_capability_catalog(); "
                "import json; "
                "print(json.dumps(sorted(catalog.data_queries)))"
            ),
        ]
    )
    assert "whatsapp.chat_context" in catalog_probe

    registry_path = tmp_path / "installed_agents.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "agent_id": "sample-agent-e2e",
                    "agent_name": "sample-agent-e2e",
                    "built_wheel": {"path": str(packaged.wheel_path)},
                }
            ]
        ),
        encoding="utf-8",
    )

    run_result = subprocess.run(
        [
            str(python_bin),
            "-m",
            "boxy_agent.cli",
            "run",
            "--agent",
            "sample-agent-e2e",
            "--registry-file",
            str(registry_path),
            "--event-json",
            '{"type": "start"}',
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(run_result.stdout)
    assert payload["status"] == "idle"
    assert payload["last_output"] == {"event_type": "start"}


def _build_sdk_wheel(output_dir: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    project_dir = repo_root / "boxy-agent"
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(project_dir / "build", ignore_errors=True)
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(output_dir),
            str(project_dir),
        ]
    )
    wheels = sorted(output_dir.glob("*.whl"))
    assert wheels
    return wheels[-1]


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, text=True, capture_output=True)


def _run_json(command: list[str]) -> list[str]:
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    return cast(list[str], payload)
