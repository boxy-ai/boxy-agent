"""Regenerate tracked capability catalog artifacts from monorepo source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> int:
    generated_packaged_catalog_matches_repo_snapshot, sync_packaged_capability_catalog = (
        _load_catalog_generation_helpers()
    )
    parser = argparse.ArgumentParser(
        prog="sync_capability_catalog.py",
        description="Regenerate the packaged capability catalog from desktop connector code.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the tracked packaged capability catalog is already up to date.",
    )
    args = parser.parse_args()

    if args.check:
        if generated_packaged_catalog_matches_repo_snapshot():
            print("Packaged capability catalog is up to date.")
            return 0
        parser.exit(
            status=1,
            message=(
                "Packaged capability catalog drift detected. Run "
                "`mise run agent:catalog-sync` and commit the updated artifacts.\n"
            ),
        )

    packaged_path = sync_packaged_capability_catalog()
    print(Path(packaged_path).resolve())
    return 0


def _load_catalog_generation_helpers():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from _catalog_generation import (
        generated_packaged_catalog_matches_repo_snapshot,
        sync_packaged_capability_catalog,
    )

    return generated_packaged_catalog_matches_repo_snapshot, sync_packaged_capability_catalog


if __name__ == "__main__":
    raise SystemExit(main())
