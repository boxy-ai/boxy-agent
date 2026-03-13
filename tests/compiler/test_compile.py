from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import write_agent_project
from test_helpers.capabilities import (
    DEFAULT_BOXY_TOOL_NAME,
    DEFAULT_DATA_QUERY_NAME,
    default_capability_catalog,
)

from boxy_agent.capabilities import load_capability_catalog
from boxy_agent.compiler import compile_agent
from boxy_agent.compiler.compile import CompilationError
from boxy_agent.compiler.metadata import MetadataValidationError

READ_ONLY_BOXY_TOOL_NAME = "google_gmail.gmail_search_threads"

BASE_SOURCE = (
    "from boxy_agent.sdk import decorators, models\n"
    "\n"
    "@decorators.agent_main\n"
    "def handle(context):\n"
    '    return models.AgentResult(output={"event": context.event.type})\n'
)

BASE_METADATA = """
[tool.boxy_agent.agent]
name = "test-agent"
description = "Test agent"
version = "1.2.3"
type = "automation"
module = "sample_agent.agent"
expected_event_types = ["start"]

[tool.boxy_agent.capabilities]
data_queries = ["whatsapp.chat_context"]
boxy_tools = []
builtin_tools = ["web_search"]
event_emitters = []
""".strip()


def _make_project(
    tmp_path: Path, *, source: str = BASE_SOURCE, metadata: str = BASE_METADATA
) -> Path:
    project_dir = tmp_path / "project"
    return write_agent_project(
        project_dir=project_dir,
        distribution_name="sample-agent-dist",
        package_name="sample_agent",
        agent_name="test-agent",
        agent_source=source,
        metadata_toml=metadata,
    )


def test_compile_agent_writes_manifest(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    output_dir = tmp_path / "output"

    compiled = compile_agent(
        project_dir=project_dir,
        output_dir=output_dir,
        capability_catalog=default_capability_catalog(),
    )

    assert compiled.manifest_path.exists()
    assert compiled.module_path == project_dir / "src" / "sample_agent" / "agent.py"
    assert compiled.manifest.entrypoint.module == "sample_agent.agent"
    assert compiled.manifest.entrypoint.function == "handle"

    payload = json.loads(compiled.manifest_path.read_text(encoding="utf-8"))
    assert payload["name"] == "test-agent"
    assert payload["type"] == "automation"
    assert payload["capabilities"]["data_queries"] == [DEFAULT_DATA_QUERY_NAME]
    assert payload["capabilities"]["event_emitters"] == []


def test_compile_rejects_missing_metadata_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)

    with pytest.raises(MetadataValidationError):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_missing_tool_metadata_table(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text(
        """
[project]
name = "sample-agent"
version = "0.1.0"
description = "No boxy metadata"
requires-python = ">=3.12"
dependencies = ["boxy-agent>=0.2.0a4,<0.3.0"]

[tool.other]
enabled = true
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(MetadataValidationError, match="boxy_agent"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_missing_decorator(tmp_path: Path) -> None:
    source = (
        "from boxy_agent.sdk import models\n"
        "\n"
        "def handle(context):\n"
        '    return models.AgentResult(output={"ok": True})\n'
    )
    project_dir = _make_project(tmp_path, source=source)

    with pytest.raises(CompilationError, match="exactly one"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_multiple_decorated_functions(tmp_path: Path) -> None:
    source = (
        "from boxy_agent.sdk import decorators, models\n"
        "\n"
        "@decorators.agent_main\n"
        "def handle(context):\n"
        '    return models.AgentResult(output={"step": 1})\n'
        "\n"
        "@decorators.agent_main\n"
        "def handle_two(context):\n"
        '    return models.AgentResult(output={"step": 2})\n'
    )
    project_dir = _make_project(tmp_path, source=source)

    with pytest.raises(CompilationError, match="multiple"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_non_canonical_signature(tmp_path: Path) -> None:
    source = (
        "from boxy_agent.sdk import decorators, models\n"
        "\n"
        "@decorators.agent_main\n"
        "def handle(event, context):\n"
        '    return models.AgentResult(output={"ok": True})\n'
    )
    project_dir = _make_project(tmp_path, source=source)

    with pytest.raises(CompilationError, match="exactly one"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_unknown_capability(tmp_path: Path) -> None:
    metadata = BASE_METADATA.replace(DEFAULT_DATA_QUERY_NAME, "unknown.data")
    project_dir = _make_project(tmp_path, metadata=metadata)

    with pytest.raises(MetadataValidationError, match="Unknown data_queries"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_uses_packaged_capability_catalog_by_default(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)

    compiled = compile_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "output",
    )

    assert compiled.manifest.capabilities.data_queries == frozenset({DEFAULT_DATA_QUERY_NAME})


def test_compile_accepts_data_mining_with_read_only_boxy_tools(tmp_path: Path) -> None:
    metadata = (
        BASE_METADATA.replace('type = "automation"', 'type = "data_mining"')
        .replace(
            'expected_event_types = ["start"]\n',
            "",
        )
        .replace(
            "boxy_tools = []",
            f'boxy_tools = ["{READ_ONLY_BOXY_TOOL_NAME}"]',
        )
    )
    project_dir = _make_project(tmp_path, metadata=metadata)

    compiled = compile_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "output",
        capability_catalog=default_capability_catalog(),
    )

    assert compiled.manifest.agent_type == "data_mining"
    assert compiled.manifest.capabilities.boxy_tools == frozenset({READ_ONLY_BOXY_TOOL_NAME})


def test_compile_rejects_data_mining_with_side_effecting_boxy_tools(tmp_path: Path) -> None:
    metadata = (
        BASE_METADATA.replace('type = "automation"', 'type = "data_mining"')
        .replace(
            'expected_event_types = ["start"]\n',
            "",
        )
        .replace(
            "boxy_tools = []",
            f'boxy_tools = ["{DEFAULT_BOXY_TOOL_NAME}"]',
        )
    )
    project_dir = _make_project(tmp_path, metadata=metadata)

    with pytest.raises(
        MetadataValidationError,
        match=f"side-effecting boxy_tools: {DEFAULT_BOXY_TOOL_NAME}",
    ):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_rejects_main_agent_type(tmp_path: Path) -> None:
    metadata = BASE_METADATA.replace('type = "automation"', 'type = "main"')
    project_dir = _make_project(tmp_path, metadata=metadata)

    with pytest.raises(MetadataValidationError, match="Unsupported agent type"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )


def test_compile_supports_injected_capability_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.toml"
    catalog_path.write_text(
        """
schema_version = 1

[[data_queries]]
name = "custom.messages"
description = "Custom message query"
input_schema = { type = "object", properties = { fts = { type = "string" } } }
output_schema = { type = "array", items = { type = "object" } }

[[boxy_tools]]
name = "custom.send"
description = "Custom send tool"
input_schema = { type = "object", properties = { body = { type = "string" } } }
output_schema = { type = "object", properties = { status = { type = "string" } } }

[[builtin_tools]]
name = "custom.web"
description = "Custom web search tool"
input_schema = { type = "object", properties = { query = { type = "string" } } }
output_schema = { type = "object" }
""".strip(),
        encoding="utf-8",
    )

    project_dir = _make_project(
        tmp_path,
        metadata="""
[tool.boxy_agent.agent]
name = "test-agent"
description = "Test agent"
version = "1.2.3"
type = "automation"
module = "sample_agent.agent"
expected_event_types = ["start"]

[tool.boxy_agent.capabilities]
data_queries = ["custom.messages"]
boxy_tools = ["custom.send"]
builtin_tools = ["custom.web"]
event_emitters = ["insight.generated"]
""".strip(),
    )

    compiled = compile_agent(
        project_dir=project_dir,
        output_dir=tmp_path / "output",
        capability_catalog=load_capability_catalog(catalog_path),
    )

    assert compiled.manifest.capabilities.data_queries == frozenset({"custom.messages"})
    assert compiled.manifest.capabilities.event_emitters == frozenset({"insight.generated"})


def test_compile_rejects_non_package_module_path(tmp_path: Path) -> None:
    project_dir = _make_project(
        tmp_path,
        metadata=BASE_METADATA.replace('module = "sample_agent.agent"', 'module = "agent"'),
    )
    # Mirror a flat module file so this fails due metadata validation,
    # rather than missing-file lookup.
    (project_dir / "agent.py").write_text(
        (project_dir / "src" / "sample_agent" / "agent.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(MetadataValidationError, match="module must be a dotted import path"):
        compile_agent(
            project_dir=project_dir,
            output_dir=tmp_path / "output",
            capability_catalog=default_capability_catalog(),
        )
