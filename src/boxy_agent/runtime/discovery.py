"""Installed agent discovery from persisted registry records."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import cast

from boxy_agent.runtime.errors import RegistrationError
from boxy_agent.runtime.models import InstalledAgent
from boxy_agent.runtime.wheel_inspection import InspectedWheelArtifact, inspect_wheel_artifact
from boxy_agent.sdk.interfaces import AgentMainFunction


@dataclass(frozen=True)
class DiscoveredAgent:
    """Resolved installed agent with callable entrypoint."""

    installed: InstalledAgent
    handler: AgentMainFunction
    wheel_path: Path | None = None


def validate_wheel_entrypoint(
    *,
    wheel_path: Path,
    agent_name: str | None = None,
) -> InspectedWheelArtifact:
    """Validate that a wheel manifest resolves to an importable callable entrypoint."""
    inspected = inspect_wheel_artifact(wheel_path=wheel_path, agent_name=agent_name)
    module_name, _function_name = _require_manifest_entrypoint(
        inspected.manifest,
        agent_name=inspected.installed.name,
    )
    root_package = module_name.split(".")[0]
    try:
        _load_handler_from_manifest(
            inspected.manifest,
            agent_name=inspected.installed.name,
            wheel_path=inspected.wheel_path,
        )
    finally:
        _unload_package_modules(root_package)
        _remove_wheel_from_sys_path(inspected.wheel_path)
    return inspected


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
        inspected = inspect_wheel_artifact(wheel_path=wheel_path, agent_name=agent_name)
        handler = _load_handler_from_manifest(
            inspected.manifest,
            agent_name=agent_name,
            wheel_path=wheel_path,
        )
        discovered[agent_name] = DiscoveredAgent(
            installed=inspected.installed,
            handler=handler,
            wheel_path=wheel_path,
        )
    return discovered


def _load_handler_from_manifest(
    manifest: dict[str, object],
    *,
    agent_name: str,
    wheel_path: Path,
) -> AgentMainFunction:
    module_name, function_name = _require_manifest_entrypoint(manifest, agent_name=agent_name)

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


def _require_manifest_entrypoint(
    manifest: dict[str, object],
    *,
    agent_name: str,
) -> tuple[str, str]:
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, dict):
        raise RegistrationError(f"Manifest key 'entrypoint' missing for agent '{agent_name}'")

    module_name = entrypoint.get("module")
    if not isinstance(module_name, str) or not module_name.strip():
        raise RegistrationError(
            f"Manifest key 'module' must be a non-empty string for agent '{agent_name}'"
        )

    function_name = entrypoint.get("function")
    if not isinstance(function_name, str) or not function_name.strip():
        raise RegistrationError(
            f"Manifest key 'function' must be a non-empty string for agent '{agent_name}'"
        )

    return module_name.strip(), function_name.strip()


def _import_module_from_wheel(*, module_name: str, wheel_path: Path, agent_name: str) -> ModuleType:
    _ensure_wheel_on_sys_path(wheel_path)

    root_package = module_name.split(".")[0]
    existing_root = sys.modules.get(root_package)
    if existing_root is not None and not _module_origin_matches_wheel(existing_root, wheel_path):
        if _module_origin_is_wheel(existing_root):
            _unload_package_modules(root_package)
        else:
            raise RegistrationError(
                f"Cannot load package '{root_package}' for '{agent_name}' from wheel "
                f"'{wheel_path}'. Package already loaded from "
                f"'{_module_origin_label(existing_root)}'"
            )

    existing_module = sys.modules.get(module_name)
    if existing_module is not None:
        if _module_origin_matches_wheel(existing_module, wheel_path):
            return existing_module
        if _module_origin_is_wheel(existing_module):
            _unload_package_modules(root_package)
        else:
            raise RegistrationError(
                f"Cannot load module '{module_name}' for '{agent_name}' from wheel "
                f"'{wheel_path}'. Module already loaded from "
                f"'{_module_origin_label(existing_module)}'"
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
    importlib.invalidate_caches()


def _remove_wheel_from_sys_path(wheel_path: Path) -> None:
    wheel_path_str = str(wheel_path)
    if wheel_path_str in sys.path:
        sys.path.remove(wheel_path_str)
        importlib.invalidate_caches()


def _unload_package_modules(root_package: str) -> None:
    package_prefix = f"{root_package}."
    module_names = sorted(
        name for name in sys.modules if name == root_package or name.startswith(package_prefix)
    )
    for module_name in reversed(module_names):
        sys.modules.pop(module_name, None)
    if module_names:
        importlib.invalidate_caches()


def _module_origin_is_wheel(module: ModuleType) -> bool:
    return _module_wheel_path(module) is not None


def _module_wheel_path(module: ModuleType) -> Path | None:
    loader = getattr(module, "__loader__", None)
    archive = getattr(loader, "archive", None)
    if isinstance(archive, str):
        try:
            return Path(archive).resolve()
        except OSError:
            return None

    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, str):
        return None

    normalized = module_file.replace("\\", "/")
    marker = ".whl/"
    if marker not in normalized:
        return None
    archive_path = normalized.split(marker, 1)[0] + ".whl"
    try:
        return Path(archive_path).resolve()
    except OSError:
        return None


def _module_origin_matches_wheel(module: ModuleType, wheel_path: Path) -> bool:
    origin_wheel_path = _module_wheel_path(module)
    if origin_wheel_path is not None:
        return origin_wheel_path == wheel_path

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
