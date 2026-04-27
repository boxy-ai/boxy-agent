"""Shared execution-affinity contract for descriptors and runtime bindings."""

from __future__ import annotations

from typing import Literal, TypeGuard, cast

ExecutionAffinity = Literal["main_thread", "worker_thread_safe"]
DEFAULT_EXECUTION_AFFINITY: ExecutionAffinity = "main_thread"


def is_execution_affinity(value: object) -> TypeGuard[ExecutionAffinity]:
    """Return whether ``value`` is one supported execution-affinity literal."""
    return isinstance(value, str) and value in {"main_thread", "worker_thread_safe"}


def require_execution_affinity(value: object, *, label: str) -> ExecutionAffinity:
    """Validate and return one supported execution-affinity literal."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not is_execution_affinity(value):
        raise ValueError(f"Unsupported {label}: {value}")
    return cast(ExecutionAffinity, value)
