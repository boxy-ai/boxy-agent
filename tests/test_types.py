from __future__ import annotations

import math

import pytest

from boxy_agent.types import ensure_json_value, is_json_value


def test_is_json_value_rejects_nan_and_infinite_floats() -> None:
    assert is_json_value(1.5)
    assert not is_json_value(float("nan"))
    assert not is_json_value(float("inf"))
    assert not is_json_value(float("-inf"))


def test_ensure_json_value_rejects_nested_non_finite_float() -> None:
    value = {"stats": {"score": math.nan}}

    with pytest.raises(TypeError, match="must be JSON-serializable"):
        ensure_json_value(value, label="payload")
