"""Installed agent discovery from persisted registry records."""

from __future__ import annotations

import importlib
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

from boxy_agent.models import AgentCapabilities, parse_agent_type
from boxy_agent.runtime.errors import RegistrationError
from boxy_agent.runtime.models import InstalledAgent
from boxy_agent.sdk.interfaces import AgentMainFunction


@dataclass(frozen=True)
class DiscoveredAgent:
    """Resolved installed agent with callable entrypoint."""

    installed: InstalledAgent
    handler: AgentMainFunction
    wheel_path: Path | None = None


def discover_registered_agents(
    records: Sequence[Mapping[str, object]],
) -> dict[str, DiscoveredAgent]:
    """
    Discover agents from a persisted registry record list.

    Expected record shape:
    - ``agent_id``: non-empty string
    - ``agent_name``: non-empty string
    - ``built_wheel``: dictionary containing at least ``path``
    """
    normalized_records: list[tuple[str, str, Path]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    # Normalize and validate the full registry first so duplicate/conflict errors
    # are deterministic and surfaced before any import side effects occur.
    for record in records:
        agent_id = _require_record_string(record, "agent_id")
        agent_name = _require_record_string(record, "agent_name")
        if agent_name in seen_names:
            raise RegistrationError(f"Duplicate agent_name in registry: {agent_name}")
        if agent_id in seen_ids:
            raise RegistrationError(f"Duplicate agent_id in registry: {agent_id}")

        wheel = _require_record_table(record, "built_wheel", agent_name=agent_name)
        wheel_path = _require_wheel_path(wheel, agent_name=agent_name)
        seen_ids.add(agent_id)
        seen_names.add(agent_name)
        normalized_records.append((agent_id, agent_name, wheel_path))

    discovered: dict[str, DiscoveredAgent] = {}
    for _agent_id, agent_name, wheel_path in normalized_records:
        manifest = _load_manifest_from_wheel(wheel_path=wheel_path, agent_name=agent_name)
        installed = _installed_agent_from_manifest(name=agent_name, payload=manifest)
        handler = _load_handler_from_manifest(
            manifest,
            agent_name=agent_name,
            wheel_path=wheel_path,
        )
        discovered[agent_name] = DiscoveredAgent(
            installed=installed,
            handler=handler,
            wheel_path=wheel_path,
        )
    return discovered


def _load_manifest_from_wheel(*, wheel_path: Path, agent_name: str) -> dict[str, object]:
    manifest_module_name = _manifest_module_name_from_wheel(
        wheel_path=wheel_path, agent_name=agent_name
    )
    module = _import_module_from_wheel(
        module_name=manifest_module_name,
        wheel_path=wheel_path,
        agent_name=agent_name,
    )
    payload = getattr(module, "COMPILED_AGENT_MANIFEST", None)
    if not isinstance(payload, dict):
        raise RegistrationError(
            "Compiled manifest module must define COMPILED_AGENT_MANIFEST as an object for "
            f"agent '{agent_name}'"
        )
    return cast(dict[str, object], payload)


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


def _load_handler_from_manifest(
    manifest: dict[str, object],
    *,
    agent_name: str,
    wheel_path: Path,
) -> AgentMainFunction:
    entrypoint = _require_table(manifest, "entrypoint", agent_name=agent_name)
    module_name = _require_string(entrypoint, "module", agent_name=agent_name)
    function_name = _require_string(entrypoint, "function", agent_name=agent_name)

    module = _import_module_from_wheel(
        module_name=module_name,
        wheel_path=wheel_path,
        agent_name=agent_name,
    )

    handler = getattr(module, function_name, None)
    if not callable(handler):
        raise RegistrationError(
            f"Entrypoint '{module_name}:{function_name}' is not callable for '{agent_name}'"
        )
    return cast(AgentMainFunction, handler)


def _import_module_from_wheel(*, module_name: str, wheel_path: Path, agent_name: str) -> ModuleType:
    _ensure_wheel_on_sys_path(wheel_path)

    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        if _module_origin_matches_wheel(existing_module, wheel_path):
            return existing_module
        raise RegistrationError(
            f"Cannot load module '{module_name}' for '{agent_name}' from wheel '{wheel_path}'. "
            f"Module already loaded from '{_module_origin_label(existing_module)}'"
        )

    root_package = module_name.split(".")[0]
    existing_root = sys.modules.get(root_package)
    if existing_root is not None and not _module_origin_matches_wheel(existing_root, wheel_path):
        raise RegistrationError(
            f"Cannot load package '{root_package}' for '{agent_name}' from wheel '{wheel_path}'. "
            f"Package already loaded from '{_module_origin_label(existing_root)}'"
        )

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        raise RegistrationError(
            f"Failed to import module '{module_name}' from wheel '{wheel_path}' for '{agent_name}'"
        ) from exc

    if not _module_origin_matches_wheel(module, wheel_path):
        raise RegistrationError(
            f"Imported module '{module_name}' for '{agent_name}' did not resolve from "
            f"wheel '{wheel_path}'"
        )
    return module


def _ensure_wheel_on_sys_path(wheel_path: Path) -> None:
    wheel_path_str = str(wheel_path)
    if wheel_path_str in sys.path:
        sys.path.remove(wheel_path_str)
    sys.path.insert(0, wheel_path_str)


def _module_origin_matches_wheel(module: ModuleType, wheel_path: Path) -> bool:
    loader = getattr(module, "__loader__", None)
    archive = getattr(loader, "archive", None)
    if isinstance(archive, str):
        try:
            if Path(archive).resolve() == wheel_path:
                return True
        except OSError:
            return False

    module_file = getattr(module, "__file__", None)
    if isinstance(module_file, str):
        module_file_norm = module_file.replace("\\", "/")
        wheel_path_norm = wheel_path.as_posix()
        return module_file_norm.startswith(f"{wheel_path_norm}/")
    return False


def _module_origin_label(module: ModuleType) -> str:
    loader = getattr(module, "__loader__", None)
    archive = getattr(loader, "archive", None)
    if isinstance(archive, str):
        return archive
    module_file = getattr(module, "__file__", None)
    if isinstance(module_file, str):
        return module_file
    return "<unknown origin>"


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


def _require_record_string(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistrationError(f"Registry key '{key}' must be a non-empty string")
    return value.strip()


def _require_record_table(
    record: Mapping[str, object],
    key: str,
    *,
    agent_name: str,
) -> dict[str, object]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise RegistrationError(f"Registry key '{key}' must be an object for '{agent_name}'")
    return cast(dict[str, object], value)


def _require_wheel_path(wheel: dict[str, object], *, agent_name: str) -> Path:
    value = wheel.get("path")
    if not isinstance(value, str) or not value.strip():
        raise RegistrationError(
            f"Registry key 'built_wheel.path' must be a non-empty string for '{agent_name}'"
        )

    wheel_path = Path(value).expanduser()
    if wheel_path.suffix != ".whl":
        raise RegistrationError(
            f"Registry key 'built_wheel.path' must point to a .whl file for '{agent_name}'"
        )
    resolved = wheel_path.resolve()
    if not resolved.exists():
        raise RegistrationError(
            f"Registry key 'built_wheel.path' does not exist for '{agent_name}': {resolved}"
        )
    return resolved
