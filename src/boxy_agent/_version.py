"""Single-source version metadata for ``boxy-agent``."""

from __future__ import annotations

__version__ = "0.2.0a6"
__requires_boxy__ = {
    "boxy_version": ">=0.2.0,<0.3.0",
    "boxy_runtime_api": ">=1,<2",
    "agent_manifest_schema": 2,
    "capability_catalog_schema": 1,
}
