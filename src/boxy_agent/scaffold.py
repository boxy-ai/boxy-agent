"""Project scaffolding helpers for ``boxy-agent`` CLI."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from boxy_agent.models import AgentType


@dataclass(frozen=True)
class CreatedAgentProject:
    """Result of creating a scaffolded agent project."""

    project_dir: Path
    agent_type: AgentType
    package_name: str


def create_agent_project(
    *,
    project_dir: Path,
    requested_type: str,
    name: str | None = None,
    description: str | None = None,
) -> CreatedAgentProject:
    """Create a new Boxy agent project scaffold."""
    agent_type = _resolve_agent_type(requested_type)
    resolved_project_dir = project_dir.resolve()
    project_name = (name or resolved_project_dir.name).strip()
    if not project_name:
        raise ValueError("Agent name must be non-empty")

    package_name = _to_package_name(project_name)
    if resolved_project_dir.exists() and any(resolved_project_dir.iterdir()):
        raise ValueError(f"Project directory must be empty: {resolved_project_dir}")

    resolved_project_dir.mkdir(parents=True, exist_ok=True)
    _write_pyproject(
        project_dir=resolved_project_dir,
        project_name=project_name,
        package_name=package_name,
        agent_type=agent_type,
        description=description,
    )
    _write_source_files(
        project_dir=resolved_project_dir,
        package_name=package_name,
        project_name=project_name,
    )
    return CreatedAgentProject(
        project_dir=resolved_project_dir,
        agent_type=agent_type,
        package_name=package_name,
    )


def _resolve_agent_type(requested_type: str) -> AgentType:
    normalized = requested_type.strip().lower().replace("_", "-")
    mapping: dict[str, AgentType] = {
        "operation": "automation",
        "data-mining": "data_mining",
    }

    if normalized not in mapping:
        allowed = ", ".join(sorted(mapping))
        raise ValueError(f"Unsupported agent type '{requested_type}'. Supported types: {allowed}")

    return mapping[normalized]


def _to_package_name(project_name: str) -> str:
    package_name = project_name.strip().lower().replace("-", "_").replace(" ", "_")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", package_name):
        raise ValueError(
            "Agent name must contain only letters, numbers, spaces, '-' or '_', "
            "and must not start with a number"
        )
    return package_name


def _write_pyproject(
    *,
    project_dir: Path,
    project_name: str,
    package_name: str,
    agent_type: AgentType,
    description: str | None,
) -> None:
    agent_description = description or f"Boxy {agent_type.replace('_', '-')} agent"
    lines = [
        "[project]",
        f"name = {_toml_string(project_name)}",
        'version = "0.1.0"',
        f"description = {_toml_string(agent_description)}",
        'requires-python = ">=3.12"',
        "dependencies = []",
        "",
        "[build-system]",
        'requires = ["setuptools>=69.0"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[tool.setuptools]",
        'package-dir = { "" = "src" }',
        "",
        "[tool.setuptools.packages.find]",
        'where = ["src"]',
        "",
        "[tool.boxy_agent.agent]",
        f"name = {_toml_string(project_name)}",
        f"description = {_toml_string(agent_description)}",
        'version = "0.1.0"',
        f"type = {_toml_string(agent_type)}",
        f"module = {_toml_string(f'{package_name}.agent')}",
    ]
    if agent_type == "automation":
        lines.append('expected_event_types = ["start"]')
    lines.extend(
        [
            "",
            "[tool.boxy_agent.capabilities]",
            "data_queries = []",
            "boxy_tools = []",
            "builtin_tools = []",
            "event_emitters = []",
            "",
        ]
    )
    (project_dir / "pyproject.toml").write_text("\n".join(lines), encoding="utf-8")


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _write_source_files(*, project_dir: Path, package_name: str, project_name: str) -> None:
    source_dir = project_dir / "src" / package_name
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "__init__.py").write_text("", encoding="utf-8")
    (source_dir / "agent.py").write_text(
        "\n".join(
            [
                "from boxy_agent.sdk import decorators, models",
                "",
                "@decorators.agent_main",
                "def handle(exec_ctx: models.AgentExecutionContext) -> models.AgentResult:",
                "    return models.AgentResult(",
                "        output={",
                f'            "agent": "{project_name}",',
                '            "event_type": exec_ctx.event.type,',
                "        }",
                "    )",
                "",
            ]
        ),
        encoding="utf-8",
    )
