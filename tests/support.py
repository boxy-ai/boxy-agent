from __future__ import annotations

import re
from pathlib import Path

from boxy_agent._version import __version__


def write_agent_project(
    *,
    project_dir: Path,
    distribution_name: str,
    package_name: str,
    agent_name: str,
    agent_module: str = "agent",
    agent_source: str,
    metadata_toml: str,
) -> Path:
    """Create a temporary agent project for compiler/package tests."""
    src_package_dir = project_dir / "src" / package_name
    src_package_dir.mkdir(parents=True, exist_ok=True)

    (src_package_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_package_dir / f"{agent_module}.py").write_text(agent_source, encoding="utf-8")

    pyproject = f"""
[project]
name = "{distribution_name}"
version = "0.1.0"
description = "Temporary agent project"
requires-python = ">=3.12"
dependencies = ["{_runtime_dependency_requirement()}"]

[build-system]
requires = ["setuptools>=69.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {{ "" = "src" }}

[tool.setuptools.packages.find]
where = ["src"]
""".strip()
    (project_dir / "pyproject.toml").write_text(
        pyproject + "\n\n" + metadata_toml.strip() + "\n",
        encoding="utf-8",
    )

    return project_dir


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
