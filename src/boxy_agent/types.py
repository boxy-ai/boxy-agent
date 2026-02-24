"""Shared JSON types for boxy_agent."""

from __future__ import annotations

import math
from typing import TypeGuard

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


def is_json_value(value: object) -> TypeGuard[JsonValue]:
    """Return whether a value is JSON-serializable under the SDK contract."""
    if value is None:
        return True
    if isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
    return False


def ensure_json_value(value: object, *, label: str) -> None:
    """Raise when a value is not JSON-serializable under the SDK contract."""
    if not is_json_value(value):
        raise TypeError(f"{label} must be JSON-serializable")
