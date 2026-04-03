"""Monorepo-only helpers to generate tracked capability catalogs."""

# pyright: reportMissingImports=false

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boxy_agent.capabilities import CapabilityCatalog


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def agent_package_dir() -> Path:
    return repo_root() / "boxy-agent" / "src" / "boxy_agent"


def builtin_capability_catalog_path() -> Path:
    return agent_package_dir() / "builtin_capability.json"


def packaged_capability_catalog_path() -> Path:
    return agent_package_dir() / "capability_catalog.json"


def _load_capability_helpers():
    if str(agent_package_dir().parent) not in sys.path:
        sys.path.insert(0, str(agent_package_dir().parent))

    from boxy_agent.capabilities import CapabilityCatalog, load_capability_catalog

    return CapabilityCatalog, load_capability_catalog


def generate_packaged_capability_catalog(
    *,
    builtin_catalog_path: Path | None = None,
) -> CapabilityCatalog:
    CapabilityCatalog, load_capability_catalog = _load_capability_helpers()
    _ensure_monorepo_import_paths()

    from boxy_desktop.connector import create_shipping_connectors
    from boxy_desktop.connector.capability_generator import build_catalog

    connectors = create_shipping_connectors()
    connector_catalog = build_catalog([connector.describe() for connector in connectors])
    builtin_catalog = load_capability_catalog(
        builtin_catalog_path or builtin_capability_catalog_path()
    )
    return CapabilityCatalog(
        data_queries=dict(connector_catalog.data_queries),
        boxy_tools=dict(connector_catalog.boxy_tools),
        builtin_tools=dict(builtin_catalog.builtin_tools),
    )


def sync_packaged_capability_catalog(
    *,
    packaged_output_path: Path | None = None,
) -> Path:
    _ensure_monorepo_import_paths()

    from boxy_desktop.worker.capabilities import write_capability_catalog

    generated = generate_packaged_capability_catalog()
    packaged_path = (packaged_output_path or packaged_capability_catalog_path()).resolve()
    write_capability_catalog(packaged_path, generated)
    return packaged_path


def generated_packaged_catalog_matches_repo_snapshot() -> bool:
    with tempfile.TemporaryDirectory(prefix="boxy-agent-catalog-check-") as temp_dir:
        temp_root = Path(temp_dir)
        generated_packaged_path = sync_packaged_capability_catalog(
            packaged_output_path=temp_root / "capability_catalog.json"
        )
        return packaged_capability_catalog_path().read_text(
            encoding="utf-8"
        ) == generated_packaged_path.read_text(encoding="utf-8")


def _ensure_monorepo_import_paths() -> None:
    repo = repo_root()
    for path in (
        repo / "boxy-agent" / "src",
        repo / "boxy-desktop" / "src",
        repo / "boxy-vm-contracts" / "src",
    ):
        rendered = str(path)
        if rendered not in sys.path:
            sys.path.insert(0, rendered)
