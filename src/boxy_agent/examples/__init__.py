"""Canonical example agent project locations."""

from __future__ import annotations

from pathlib import Path

CANONICAL_AUTOMATION_EMAIL_AGENT_NAME = "canonical-automation-email-agent"
CANONICAL_DATA_MINING_EMAIL_AGENT_NAME = "canonical-data-mining-email-agent"


def canonical_automation_email_agent_project_dir() -> Path:
    """Return the canonical automation email-agent example project directory."""
    return Path(__file__).resolve().parent / "automation"


def canonical_data_mining_email_agent_project_dir() -> Path:
    """Return the canonical data-mining email-agent example project directory."""
    return Path(__file__).resolve().parent / "data_mining"


__all__ = [
    "CANONICAL_AUTOMATION_EMAIL_AGENT_NAME",
    "CANONICAL_DATA_MINING_EMAIL_AGENT_NAME",
    "canonical_automation_email_agent_project_dir",
    "canonical_data_mining_email_agent_project_dir",
]
