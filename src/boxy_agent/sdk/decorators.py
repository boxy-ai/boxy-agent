"""Namespaced decorator utilities for SDK consumers."""

from __future__ import annotations

from boxy_agent.public_sdk.decorators import (
    EntrypointMetadata,
    agent_main,
    get_entrypoint_metadata,
    is_canonical_entrypoint,
)

__all__ = [
    "EntrypointMetadata",
    "agent_main",
    "get_entrypoint_metadata",
    "is_canonical_entrypoint",
]
