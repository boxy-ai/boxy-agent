from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from support import write_agent_project
from test_helpers.capabilities import empty_capability_catalog

from boxy_agent.compiler import package_agent


def test_package_install_and_run_in_venv(tmp_path: Path) -> None:
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
        capability_catalog=empty_capability_catalog(),
    )

    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    python_bin = venv_dir / "bin" / "python"
    repo_agent_dir = Path(__file__).resolve().parents[2]
    capability_catalog_path = tmp_path / "catalog.toml"
    capability_catalog_path.write_text(
        """
schema_version = 1
data_queries = []
boxy_tools = []
builtin_tools = []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    subprocess.run([str(python_bin), "-m", "pip", "install", "-q", str(repo_agent_dir)], check=True)

    examples_probe = subprocess.run(
        [
            str(python_bin),
            "-c",
            (
                "from boxy_agent.examples import canonical_main_agent_project_dir;"
                " print((canonical_main_agent_project_dir() / 'pyproject.toml').exists())"
            ),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert examples_probe.stdout.strip() == "True"

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
            "--capability-catalog",
            str(capability_catalog_path),
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
