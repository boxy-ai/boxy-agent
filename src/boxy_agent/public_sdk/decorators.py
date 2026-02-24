"""Decorators for canonical public agent entrypoint declaration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import overload

_ENTRYPOINT_METADATA_ATTR = "__boxy_agent_main__"


@dataclass(frozen=True)
class EntrypointMetadata:
    """Metadata attached to functions marked as the canonical agent main."""

    is_canonical_main: bool = True


@overload
def agent_main[F: Callable[..., object]](function: F) -> F: ...


@overload
def agent_main[F: Callable[..., object]](function: None = None) -> Callable[[F], F]: ...


def agent_main[F: Callable[..., object]](function: F | None = None) -> Callable[[F], F] | F:
    """Mark a function as the canonical agent main entrypoint."""

    def decorator(target: F) -> F:
        setattr(target, _ENTRYPOINT_METADATA_ATTR, EntrypointMetadata())
        return target

    if function is not None:
        return decorator(function)
    return decorator


def get_entrypoint_metadata(function: object) -> EntrypointMetadata | None:
    """Return attached entrypoint metadata if present."""
    metadata = getattr(function, _ENTRYPOINT_METADATA_ATTR, None)
    if isinstance(metadata, EntrypointMetadata):
        return metadata
    return None


def is_canonical_entrypoint(function: object) -> bool:
    """Return whether a function is marked as canonical main."""
    return get_entrypoint_metadata(function) is not None
