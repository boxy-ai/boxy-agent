"""Regenerate tracked capability catalog artifacts from monorepo source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> int:
    generated_catalog_matches_repo_snapshot, sync_capability_catalogs = (
        _load_catalog_generation_helpers()
    )
    parser = argparse.ArgumentParser(
        prog="sync_capability_catalog.py",
        description="Regenerate packaged capability catalogs from desktop connector code.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that tracked capability catalogs are already up to date.",
    )
    args = parser.parse_args()

    if args.check:
        if generated_catalog_matches_repo_snapshot():
            print("Capability catalogs are up to date.")
            return 0
        parser.exit(
            status=1,
            message=(
                "Capability catalog drift detected. Run "
                "`mise run agent:catalog-sync` and commit the updated artifacts.\n"
            ),
        )

    connector_path, packaged_path = sync_capability_catalogs()
    print(Path(connector_path).resolve())
    print(Path(packaged_path).resolve())
    return 0


def _load_catalog_generation_helpers():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from _catalog_generation import (
        generated_catalog_matches_repo_snapshot,
        sync_capability_catalogs,
    )

    return generated_catalog_matches_repo_snapshot, sync_capability_catalogs


if __name__ == "__main__":
    raise SystemExit(main())
