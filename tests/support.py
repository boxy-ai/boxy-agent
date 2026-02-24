from __future__ import annotations

from pathlib import Path


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
dependencies = []

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
