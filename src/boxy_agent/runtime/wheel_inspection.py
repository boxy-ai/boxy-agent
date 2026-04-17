"""Wheel metadata inspection and manifest validation for installed agents."""

from __future__ import annotations

import ast
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from boxy_agent.compatibility import (
    CompatibilityError,
    current_boxy_agent_version,
    require_agent_sdk_compatible,
)
from boxy_agent.compiler.models import MANIFEST_SCHEMA_VERSION
from boxy_agent.models import AgentCapabilities, parse_agent_type
from boxy_agent.runtime.errors import RegistrationError
from boxy_agent.runtime.models import InstalledAgent


@dataclass(frozen=True)
class InspectedWheelArtifact:
    """Validated wheel metadata loaded without importing wheel modules."""

    wheel_path: Path
    manifest_module_name: str
    manifest: dict[str, object]
    installed: InstalledAgent


def inspect_wheel_artifact(
    *,
    wheel_path: Path,
    agent_name: str | None = None,
) -> InspectedWheelArtifact:
    """Inspect wheel metadata without importing the wheel into the current process."""
    resolved_wheel_path = wheel_path.expanduser().resolve()
    manifest_label = _manifest_error_label(agent_name=agent_name, wheel_path=resolved_wheel_path)
    manifest_module_name = _manifest_module_name_from_wheel(
        wheel_path=resolved_wheel_path,
        agent_name=manifest_label,
    )
    manifest = _load_manifest_from_wheel_source(
        wheel_path=resolved_wheel_path,
        agent_name=manifest_label,
        manifest_module_name=manifest_module_name,
    )
    expected_name = agent_name or _require_string(manifest, "name", agent_name=manifest_label)
    _require_manifest_schema_version(manifest, agent_name=expected_name)
    try:
        require_agent_sdk_compatible(
            agent_manifest=manifest,
            sdk_version=current_boxy_agent_version(),
            agent_name=expected_name,
        )
    except CompatibilityError as exc:
        raise RegistrationError(str(exc)) from exc
    installed = _installed_agent_from_manifest(name=expected_name, payload=manifest)
    return InspectedWheelArtifact(
        wheel_path=resolved_wheel_path,
        manifest_module_name=manifest_module_name,
        manifest=manifest,
        installed=installed,
    )


def _load_manifest_from_wheel_source(
    *,
    wheel_path: Path,
    agent_name: str,
    manifest_module_name: str,
) -> dict[str, object]:
    module_member_path = _manifest_member_path_from_module_name(
        manifest_module_name=manifest_module_name,
        wheel_path=wheel_path,
        agent_name=agent_name,
    )
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            with wheel.open(module_member_path, mode="r") as manifest_file:
                manifest_source = manifest_file.read().decode("utf-8")
    except KeyError as exc:
        raise RegistrationError(
            f"Wheel for '{agent_name}' is missing manifest module source: {manifest_module_name}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise RegistrationError(
            f"Manifest module is not valid UTF-8 for agent '{agent_name}'"
        ) from exc

    return _manifest_payload_from_source(manifest_source, agent_name=agent_name)


def _manifest_error_label(*, agent_name: str | None, wheel_path: Path) -> str:
    if agent_name is not None:
        return agent_name
    return wheel_path.name


def _manifest_payload_from_source(source: str, *, agent_name: str) -> dict[str, object]:
    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        raise RegistrationError(
            f"Manifest module could not be parsed for agent '{agent_name}'"
        ) from exc

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == "COMPILED_AGENT_MANIFEST":
                    return _manifest_payload_from_node(statement.value, agent_name=agent_name)
        if isinstance(statement, ast.AnnAssign):
            target = statement.target
            if isinstance(target, ast.Name) and target.id == "COMPILED_AGENT_MANIFEST":
                if statement.value is None:
                    break
                return _manifest_payload_from_node(statement.value, agent_name=agent_name)

    raise RegistrationError(
        "Compiled manifest module must define COMPILED_AGENT_MANIFEST as an object for "
        f"agent '{agent_name}'"
    )


def _manifest_payload_from_node(node: ast.AST, *, agent_name: str) -> dict[str, object]:
    payload: object
    if isinstance(node, ast.Call) and _is_json_loads_call(node):
        if len(node.args) != 1 or node.keywords:
            raise RegistrationError(
                f"Compiled manifest loader must be json.loads(<string>) for agent '{agent_name}'"
            )
        payload_arg = node.args[0]
        if not isinstance(payload_arg, ast.Constant) or not isinstance(payload_arg.value, str):
            raise RegistrationError(
                f"Compiled manifest payload must be encoded as a JSON string for agent "
                f"'{agent_name}'"
            )
        try:
            payload = json.loads(payload_arg.value)
        except json.JSONDecodeError as exc:
            raise RegistrationError(
                f"Compiled manifest JSON is invalid for agent '{agent_name}'"
            ) from exc
    else:
        try:
            payload = ast.literal_eval(node)
        except (SyntaxError, ValueError) as exc:
            raise RegistrationError(
                f"Compiled manifest payload could not be evaluated for agent '{agent_name}'"
            ) from exc

    if not isinstance(payload, dict):
        raise RegistrationError(
            "Compiled manifest module must define COMPILED_AGENT_MANIFEST as an object for "
            f"agent '{agent_name}'"
        )
    return cast(dict[str, object], payload)


def _is_json_loads_call(node: ast.Call) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "loads"
        and isinstance(function.value, ast.Name)
        and function.value.id == "json"
    )


def _manifest_member_path_from_module_name(
    *,
    manifest_module_name: str,
    wheel_path: Path,
    agent_name: str,
) -> str:
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            members = set(wheel.namelist())
    except zipfile.BadZipFile as exc:
        raise RegistrationError(
            f"Wheel artifact is not a valid zip file for '{agent_name}': {wheel_path}"
        ) from exc

    module_parts = manifest_module_name.split(".")
    direct_path = "/".join((*module_parts[:-1], "boxy_agent_compiled_manifest.py"))
    if direct_path in members:
        return direct_path

    purelib_path = "/".join(
        (
            f"{module_parts[0]}.data",
            "purelib",
            *module_parts[:-1],
            "boxy_agent_compiled_manifest.py",
        )
    )
    if purelib_path in members:
        return purelib_path

    platlib_path = "/".join(
        (
            f"{module_parts[0]}.data",
            "platlib",
            *module_parts[:-1],
            "boxy_agent_compiled_manifest.py",
        )
    )
    if platlib_path in members:
        return platlib_path

    raise RegistrationError(
        f"Wheel for '{agent_name}' is missing embedded compiled manifest module"
    )


def _manifest_module_name_from_wheel(*, wheel_path: Path, agent_name: str) -> str:
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            module_names = sorted(
                {
                    module_name
                    for member in wheel.namelist()
                    if (module_name := _module_name_for_manifest_member(member)) is not None
                }
            )
    except zipfile.BadZipFile as exc:
        raise RegistrationError(
            f"Wheel artifact is not a valid zip file for '{agent_name}': {wheel_path}"
        ) from exc

    if not module_names:
        raise RegistrationError(
            f"Wheel for '{agent_name}' is missing embedded compiled manifest module"
        )
    if len(module_names) > 1:
        rendered = ", ".join(module_names)
        raise RegistrationError(
            f"Wheel for '{agent_name}' defines multiple compiled manifest modules: {rendered}"
        )
    return module_names[0]


def _module_name_for_manifest_member(member: str) -> str | None:
    if not member.endswith("/boxy_agent_compiled_manifest.py"):
        return None

    parts = tuple(part for part in member.split("/") if part)
    if not parts:
        return None

    module_parts: tuple[str, ...]
    if parts[0].endswith(".data"):
        if len(parts) < 4 or parts[1] not in {"purelib", "platlib"}:
            return None
        module_parts = parts[2:-1]
    else:
        module_parts = parts[:-1]

    if not module_parts:
        return None
    if any(not segment.isidentifier() for segment in module_parts):
        return None
    return ".".join((*module_parts, "boxy_agent_compiled_manifest"))


def _installed_agent_from_manifest(*, name: str, payload: object) -> InstalledAgent:
    if not isinstance(payload, dict):
        raise RegistrationError(f"Manifest entry point for '{name}' must load a dictionary")

    manifest = cast(dict[str, object], payload)
    capabilities_table = _require_table(manifest, "capabilities", agent_name=name)

    installed_name = _require_string(manifest, "name", agent_name=name)
    if installed_name != name:
        raise RegistrationError(
            f"Manifest name mismatch for '{name}': manifest declares '{installed_name}'"
        )

    description = _require_string(manifest, "description", agent_name=name)
    version = _require_string(manifest, "version", agent_name=name)
    agent_type = parse_agent_type(_require_string(manifest, "type", agent_name=name))
    expected_event_types = tuple(
        _optional_string_list(manifest, "expected_event_types", agent_name=name)
    )

    capabilities = AgentCapabilities(
        data_queries=frozenset(
            _optional_string_list(capabilities_table, "data_queries", agent_name=name)
        ),
        boxy_tools=frozenset(
            _optional_string_list(capabilities_table, "boxy_tools", agent_name=name)
        ),
        builtin_tools=frozenset(
            _optional_string_list(capabilities_table, "builtin_tools", agent_name=name)
        ),
        event_emitters=frozenset(
            _optional_string_list(capabilities_table, "event_emitters", agent_name=name)
        ),
    )

    return InstalledAgent(
        name=name,
        description=description,
        version=version,
        agent_type=agent_type,
        expected_event_types=expected_event_types,
        capabilities=capabilities,
    )


def _require_table(data: dict[str, object], key: str, *, agent_name: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RegistrationError(f"Manifest key '{key}' missing for agent '{agent_name}'")
    return cast(dict[str, object], value)


def _require_string(data: dict[str, object], key: str, *, agent_name: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistrationError(
            f"Manifest key '{key}' must be a non-empty string for agent '{agent_name}'"
        )
    return value.strip()


def _require_int(data: dict[str, object], key: str, *, agent_name: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistrationError(f"Manifest key '{key}' must be an integer for agent '{agent_name}'")
    return value


def _require_manifest_schema_version(manifest: dict[str, object], *, agent_name: str) -> None:
    schema_version = _require_int(manifest, "schema_version", agent_name=agent_name)
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise RegistrationError(
            f"Unsupported manifest schema_version for agent '{agent_name}': "
            f"{schema_version} (expected {MANIFEST_SCHEMA_VERSION})"
        )


def _optional_string_list(data: dict[str, object], key: str, *, agent_name: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RegistrationError(f"Manifest key '{key}' must be a list for agent '{agent_name}'")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RegistrationError(
                f"Manifest key '{key}' must contain non-empty strings for agent '{agent_name}'"
            )
        normalized.append(item.strip())
    return normalized
