"""Configuration for the built-in main agent."""

from __future__ import annotations

import os
from dataclasses import dataclass

_DEFAULT_MODEL = "anthropic/claude-opus-4.6"
_DEFAULT_MAX_ITERATIONS = 20
_DEFAULT_TOP_K = 12
_MAX_TOP_K = 20


@dataclass(frozen=True)
class MainAgentConfig:
    model: str
    max_iterations: int
    top_k: int


def load_main_agent_config() -> MainAgentConfig:
    model = os.getenv("BOXY_MAIN_AGENT_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    max_iterations = _read_positive_int(
        "BOXY_MAIN_AGENT_MAX_ITERATIONS",
        default=_DEFAULT_MAX_ITERATIONS,
    )
    top_k_raw = _read_positive_int("BOXY_MAIN_AGENT_TOP_K", default=_DEFAULT_TOP_K)
    top_k = min(top_k_raw, _MAX_TOP_K)
    return MainAgentConfig(model=model, max_iterations=max_iterations, top_k=top_k)


def _read_positive_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value
