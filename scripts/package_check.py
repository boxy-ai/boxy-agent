"""Validate built boxy-agent artifacts in a clean virtual environment."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import tomllib
from pathlib import Path

from boxy_agent._version import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_DIR = REPO_ROOT / "boxy-agent"
DIST_DIR = PROJECT_DIR / "dist"


def main() -> int:
    wheel_path = _require_single_artifact("*.whl")
    _require_single_artifact("*.tar.gz")

    with tempfile.TemporaryDirectory(prefix="boxy-agent-package-check-") as temp_dir:
        temp_root = Path(temp_dir)
        python_bin = _create_venv(temp_root / "venv")
        _run(
            [
                str(python_bin),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "build",
                "setuptools",
                "wheel",
            ]
        )
        _run([str(python_bin), "-m", "pip", "install", str(wheel_path)])

        _assert_packaged_catalog(python_bin)
        _check_scaffolded_agent_flow(python_bin, temp_root / "scaffolded-agent")
        _check_authored_agent_flow(python_bin, temp_root / "authored-agent")
        _check_llm_unconfigured_error(python_bin, temp_root / "llm-agent")
        _check_web_search_unconfigured_error(python_bin, temp_root / "web-search-agent")

    print("boxy-agent package check passed")
    return 0


def _require_single_artifact(pattern: str) -> Path:
    matches = sorted(DIST_DIR.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one dist/{pattern} artifact, found {len(matches)}")
    return matches[0].resolve()


def _create_venv(venv_dir: Path) -> Path:
    _run(["uv", "venv", "--seed", str(venv_dir)])
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return venv_dir / scripts_dir / executable


def _assert_packaged_catalog(python_bin: Path) -> None:
    payload = _run_json(
        [
            str(python_bin),
            "-c",
            textwrap.dedent(
                """
                import json

                from boxy_agent.capabilities import load_packaged_capability_catalog

                catalog = load_packaged_capability_catalog()
                print(
                    json.dumps(
                        {
                            "data_queries": sorted(catalog.data_queries),
                            "boxy_tools": sorted(catalog.boxy_tools),
                            "builtin_tools": sorted(catalog.builtin_tools),
                        }
                    )
                )
                """
            ),
        ]
    )
    assert "whatsapp.chat_context" in payload["data_queries"]
    assert "whatsapp.send_message" in payload["boxy_tools"]
    assert "web_search" in payload["builtin_tools"]


def _check_scaffolded_agent_flow(python_bin: Path, project_dir: Path) -> None:
    _run_cli(
        python_bin,
        "create-agent",
        "automation",
        "--project-dir",
        str(project_dir),
        "--name",
        "scaffolded-agent",
    )

    pyproject = tomllib.loads((project_dir / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["dependencies"] == [_runtime_dependency_requirement()]

    wheel_path = _package_project(python_bin, project_dir, project_dir / "dist")
    payload = _run_packaged_agent(
        python_bin,
        agent_name="scaffolded-agent",
        wheel_path=wheel_path,
        event={"type": "start"},
    )
    assert payload["status"] == "idle"
    assert payload["last_output"] == {"agent": "scaffolded-agent", "event_type": "start"}


def _check_authored_agent_flow(python_bin: Path, project_dir: Path) -> None:
    _write_agent_project(
        project_dir=project_dir,
        distribution_name="authored-agent",
        package_name="authored_agent",
        agent_name="authored-agent",
        capabilities={
            "data_queries": [],
            "boxy_tools": [],
            "builtin_tools": [],
            "event_emitters": [],
        },
        source="""
from boxy_agent.sdk import decorators, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    return models.AgentResult(
        output={
            "agent": "authored-agent",
            "event_type": exec_ctx.event.type,
        }
    )
""",
    )

    wheel_path = _package_project(python_bin, project_dir, project_dir / "dist")
    payload = _run_packaged_agent(
        python_bin,
        agent_name="authored-agent",
        wheel_path=wheel_path,
        event={"type": "start"},
    )
    assert payload["status"] == "idle"
    assert payload["last_output"] == {"agent": "authored-agent", "event_type": "start"}


def _check_llm_unconfigured_error(python_bin: Path, project_dir: Path) -> None:
    _write_agent_project(
        project_dir=project_dir,
        distribution_name="llm-agent",
        package_name="llm_agent",
        agent_name="llm-agent",
        capabilities={
            "data_queries": [],
            "boxy_tools": [],
            "builtin_tools": [],
            "event_emitters": [],
        },
        source="""
from boxy_agent.sdk import decorators, llm, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    response = llm.chat_complete(
        exec_ctx,
        {
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    return models.AgentResult(output=response)
""",
    )

    wheel_path = _package_project(python_bin, project_dir, project_dir / "dist")
    result = _run_cli(
        python_bin,
        "run",
        "--agent",
        "llm-agent",
        "--registry-file",
        str(_write_registry(project_dir / "registry.json", "llm-agent", wheel_path)),
        "--event-json",
        json.dumps({"type": "start"}),
        check=False,
    )
    assert result.returncode == 1
    assert "No LLM client configured" in result.stderr


def _check_web_search_unconfigured_error(python_bin: Path, project_dir: Path) -> None:
    _write_agent_project(
        project_dir=project_dir,
        distribution_name="web-search-agent",
        package_name="web_search_agent",
        agent_name="web-search-agent",
        capabilities={
            "data_queries": [],
            "boxy_tools": [],
            "builtin_tools": ["web_search"],
            "event_emitters": [],
        },
        source="""
from boxy_agent.sdk import builtin_tools, decorators, models


@decorators.agent_main
def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:
    response = builtin_tools.call(exec_ctx, "web_search", {"query": "boxy"})
    return models.AgentResult(output=response)
""",
    )

    wheel_path = _package_project(python_bin, project_dir, project_dir / "dist")
    result = _run_cli(
        python_bin,
        "run",
        "--agent",
        "web-search-agent",
        "--registry-file",
        str(_write_registry(project_dir / "registry.json", "web-search-agent", wheel_path)),
        "--event-json",
        json.dumps({"type": "start"}),
        check=False,
    )
    assert result.returncode == 1
    assert "web_search is not implemented in boxy-agent runtime" in result.stderr


def _package_project(python_bin: Path, project_dir: Path, output_dir: Path) -> Path:
    package_result = _run_cli(
        python_bin,
        "package",
        "--project-dir",
        str(project_dir),
        "--output-dir",
        str(output_dir),
    )
    wheel_path = Path(package_result.stdout.strip())
    assert wheel_path.exists()
    return wheel_path


def _run_packaged_agent(
    python_bin: Path,
    *,
    agent_name: str,
    wheel_path: Path,
    event: dict[str, object],
) -> dict[str, object]:
    registry_path = _write_registry(
        wheel_path.parent / f"{agent_name}-registry.json",
        agent_name,
        wheel_path,
    )
    result = _run_cli(
        python_bin,
        "run",
        "--agent",
        agent_name,
        "--registry-file",
        str(registry_path),
        "--event-json",
        json.dumps(event),
    )
    return json.loads(result.stdout)


def _write_registry(path: Path, agent_name: str, wheel_path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "agent_id": agent_name,
                    "agent_name": agent_name,
                    "built_wheel": {"path": str(wheel_path)},
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_agent_project(
    *,
    project_dir: Path,
    distribution_name: str,
    package_name: str,
    agent_name: str,
    capabilities: dict[str, list[str]],
    source: str,
) -> None:
    source_dir = project_dir / "src" / package_name
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "__init__.py").write_text("", encoding="utf-8")
    (source_dir / "agent.py").write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    pyproject = f"""
[project]
name = "{distribution_name}"
version = "0.1.0"
description = "{distribution_name}"
requires-python = ">=3.12"
dependencies = ["{_runtime_dependency_requirement()}"]

[build-system]
requires = ["setuptools>=69.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {{ "" = "src" }}

[tool.setuptools.packages.find]
where = ["src"]

[tool.boxy_agent.agent]
name = "{agent_name}"
description = "{distribution_name}"
version = "0.1.0"
type = "automation"
module = "{package_name}.agent"
expected_event_types = ["start"]

[tool.boxy_agent.capabilities]
data_queries = {json.dumps(capabilities["data_queries"])}
boxy_tools = {json.dumps(capabilities["boxy_tools"])}
builtin_tools = {json.dumps(capabilities["builtin_tools"])}
event_emitters = {json.dumps(capabilities["event_emitters"])}
""".strip()
    (project_dir / "pyproject.toml").write_text(pyproject + "\n", encoding="utf-8")


def _runtime_dependency_requirement() -> str:
    match = re.fullmatch(
        r"(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?P<suffix>[A-Za-z0-9.-]+)?",
        __version__,
    )
    if match is None:
        raise ValueError(f"Unsupported boxy-agent version format: {__version__}")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    return f"boxy-agent>={__version__},<{major}.{minor + 1}.0"


def _run_cli(python_bin: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run([str(python_bin), "-m", "boxy_agent.cli", *args], check=check)


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _run_json(command: list[str]) -> dict[str, list[str]]:
    result = _run(command)
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
