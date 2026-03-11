"""Monorepo-only helpers to generate tracked capability catalogs."""

# pyright: reportMissingImports=false

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from boxy_agent.capabilities import CapabilityCatalog


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def agent_package_dir() -> Path:
    return repo_root() / "boxy-agent" / "src" / "boxy_agent"


def builtin_capability_catalog_path() -> Path:
    return agent_package_dir() / "builtin_capability.toml"


def packaged_capability_catalog_path() -> Path:
    return agent_package_dir() / "capability_catalog.toml"


def desktop_connector_catalog_path() -> Path:
    return repo_root() / "boxy-desktop" / "connector_capability.toml"


def _load_capability_helpers():
    if str(agent_package_dir().parent) not in sys.path:
        sys.path.insert(0, str(agent_package_dir().parent))

    from boxy_agent.capabilities import CapabilityCatalog, load_capability_catalog

    return CapabilityCatalog, load_capability_catalog


SHIPPING_CONNECTOR_IDS: tuple[str, ...] = ("local_files", "whatsapp", "wechat")


@dataclass(frozen=True)
class GeneratedCapabilityCatalogs:
    connector_catalog: CapabilityCatalog
    packaged_catalog: CapabilityCatalog


def generate_capability_catalogs(
    *,
    builtin_catalog_path: Path | None = None,
) -> GeneratedCapabilityCatalogs:
    CapabilityCatalog, load_capability_catalog = _load_capability_helpers()
    _ensure_monorepo_import_paths()

    from boxy_desktop.connector.apps.local_files.connector import (
        LocalFilesConnector,
        LocalFilesConnectorConfig,
    )
    from boxy_desktop.connector.apps.wechat import WechatConnector
    from boxy_desktop.connector.apps.whatsapp import WhatsappConnector
    from boxy_desktop.connector.capability_generator import build_catalog

    connectors = (
        ("local_files", LocalFilesConnector(config=LocalFilesConnectorConfig())),
        ("whatsapp", WhatsappConnector()),
        ("wechat", WechatConnector()),
    )
    connector_ids = tuple(connector_id for connector_id, _connector in connectors)
    if connector_ids != SHIPPING_CONNECTOR_IDS:
        raise RuntimeError(
            "Shipping connector profile mismatch: "
            f"expected {SHIPPING_CONNECTOR_IDS}, got {connector_ids}"
        )

    connector_catalog = build_catalog(
        [connector.describe() for _connector_id, connector in connectors]
    )
    builtin_catalog = load_capability_catalog(
        builtin_catalog_path or builtin_capability_catalog_path()
    )
    return GeneratedCapabilityCatalogs(
        connector_catalog=connector_catalog,
        packaged_catalog=CapabilityCatalog(
            data_queries=dict(connector_catalog.data_queries),
            boxy_tools=dict(connector_catalog.boxy_tools),
            builtin_tools=dict(builtin_catalog.builtin_tools),
        ),
    )


def sync_capability_catalogs(
    *,
    connector_output_path: Path | None = None,
    packaged_output_path: Path | None = None,
) -> tuple[Path, Path]:
    _ensure_monorepo_import_paths()

    from boxy_desktop.connector.capability_generator import write_catalog
    from boxy_desktop.worker.capabilities import write_capability_catalog

    generated = generate_capability_catalogs()
    connector_path = (connector_output_path or desktop_connector_catalog_path()).resolve()
    packaged_path = (packaged_output_path or packaged_capability_catalog_path()).resolve()
    write_catalog(connector_path, generated.connector_catalog)
    write_capability_catalog(packaged_path, generated.packaged_catalog)
    return connector_path, packaged_path


def generated_catalog_matches_repo_snapshot() -> bool:
    with tempfile.TemporaryDirectory(prefix="boxy-agent-catalog-check-") as temp_dir:
        temp_root = Path(temp_dir)
        generated_connector_path, generated_packaged_path = sync_capability_catalogs(
            connector_output_path=temp_root / "connector_capability.toml",
            packaged_output_path=temp_root / "capability_catalog.toml",
        )
        return desktop_connector_catalog_path().read_text(
            encoding="utf-8"
        ) == generated_connector_path.read_text(
            encoding="utf-8"
        ) and packaged_capability_catalog_path().read_text(
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
