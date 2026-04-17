"""Compatibility contracts between agents, the SDK, and Boxy runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from boxy_agent._version import __requires_boxy__, __version__
from boxy_agent.types import JsonValue

BOXY_AGENT_DISTRIBUTION_NAME = "boxy-agent"


class CompatibilityError(ValueError):
    """Raised when an agent, SDK, or Boxy runtime compatibility contract fails."""


@dataclass(frozen=True)
class BoxyRuntimeProvides:
    """Runtime contract surface supplied by a Boxy Desktop build."""

    boxy_version: str
    boxy_runtime_api: int
    agent_manifest_schema: int
    capability_catalog_schema: int

    def to_dict(self) -> dict[str, JsonValue]:
        """Serialize the provided runtime contract to JSON-compatible data."""
        return {
            "boxy_version": self.boxy_version,
            "boxy_runtime_api": self.boxy_runtime_api,
            "agent_manifest_schema": self.agent_manifest_schema,
            "capability_catalog_schema": self.capability_catalog_schema,
        }


def current_boxy_agent_requires_boxy() -> dict[str, JsonValue]:
    """Return the Boxy runtime contract required by this ``boxy-agent`` SDK build."""
    return cast(dict[str, JsonValue], dict(__requires_boxy__))


def current_boxy_agent_version() -> str:
    """Return the installed ``boxy-agent`` SDK version."""
    return __version__


def extract_boxy_agent_requirement(*, dependencies: list[str], source: str) -> str:
    """Return the ``boxy-agent`` dependency specifier declared by an agent project."""
    for dependency in dependencies:
        try:
            requirement = Requirement(dependency)
        except InvalidRequirement as exc:
            raise CompatibilityError(f"{source} dependency is invalid: {dependency!r}") from exc
        if canonicalize_name(requirement.name) != BOXY_AGENT_DISTRIBUTION_NAME:
            continue
        if requirement.url is not None:
            raise CompatibilityError(
                f"{source} must depend on {BOXY_AGENT_DISTRIBUTION_NAME} by version range, "
                "not by direct URL"
            )
        if requirement.marker is not None:
            raise CompatibilityError(
                f"{source} {BOXY_AGENT_DISTRIBUTION_NAME} dependency must not use markers"
            )
        specifier = str(requirement.specifier).strip()
        if not specifier:
            raise CompatibilityError(
                f"{source} must declare a non-empty {BOXY_AGENT_DISTRIBUTION_NAME} version range"
            )
        return specifier
    raise CompatibilityError(f"{source} must declare a {BOXY_AGENT_DISTRIBUTION_NAME} dependency")


def require_agent_sdk_compatible(
    *,
    agent_manifest: dict[str, object],
    sdk_version: str,
    agent_name: str,
) -> None:
    """Validate that an agent manifest can run on the selected SDK version."""
    requires = _require_table(agent_manifest, "requires", label=f"agent '{agent_name}' manifest")
    specifier = _require_non_empty_string(
        requires,
        BOXY_AGENT_DISTRIBUTION_NAME,
        label=f"agent '{agent_name}' manifest requires",
    )
    _require_version_in_specifier(
        version=sdk_version,
        specifier=specifier,
        subject=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version}",
        requirement_label=f"agent '{agent_name}' requires {BOXY_AGENT_DISTRIBUTION_NAME}",
    )


def require_boxy_agent_requirement_satisfied(
    *,
    specifier: str,
    sdk_version: str,
    source: str,
) -> None:
    """Validate that a ``boxy-agent`` dependency range includes the active SDK."""
    _require_version_in_specifier(
        version=sdk_version,
        specifier=specifier,
        subject=f"{BOXY_AGENT_DISTRIBUTION_NAME} compiler SDK {sdk_version}",
        requirement_label=f"{source} {BOXY_AGENT_DISTRIBUTION_NAME} dependency",
    )


def require_boxy_runtime_compatible(
    *,
    requires_boxy: Mapping[str, object],
    provides: BoxyRuntimeProvides,
    sdk_version: str,
) -> None:
    """Validate that the current Boxy runtime satisfies the SDK's runtime requirement."""
    required_boxy_version = _require_non_empty_string(
        requires_boxy,
        "boxy_version",
        label=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires_boxy",
    )
    _require_version_in_specifier(
        version=provides.boxy_version,
        specifier=required_boxy_version,
        subject=f"Boxy {provides.boxy_version}",
        requirement_label=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires Boxy",
    )

    required_runtime_api = _require_non_empty_string(
        requires_boxy,
        "boxy_runtime_api",
        label=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires_boxy",
    )
    _require_version_in_specifier(
        version=str(provides.boxy_runtime_api),
        specifier=required_runtime_api,
        subject=f"Boxy agent runtime API {provides.boxy_runtime_api}",
        requirement_label=(
            f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires Boxy agent runtime API"
        ),
    )

    _require_exact_int(
        actual=provides.agent_manifest_schema,
        expected=_require_int(
            requires_boxy,
            "agent_manifest_schema",
            label=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires_boxy",
        ),
        subject="agent_manifest_schema",
        sdk_version=sdk_version,
    )
    _require_exact_int(
        actual=provides.capability_catalog_schema,
        expected=_require_int(
            requires_boxy,
            "capability_catalog_schema",
            label=f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requires_boxy",
        ),
        subject="capability_catalog_schema",
        sdk_version=sdk_version,
    )


def _require_version_in_specifier(
    *,
    version: str,
    specifier: str,
    subject: str,
    requirement_label: str,
) -> None:
    try:
        parsed_version = Version(version)
    except InvalidVersion as exc:
        raise CompatibilityError(f"{subject} is not a valid version") from exc
    try:
        parsed_specifier = SpecifierSet(specifier)
    except InvalidSpecifier as exc:
        message = f"{requirement_label} has invalid specifier {specifier!r}"
        raise CompatibilityError(message) from exc
    if not parsed_specifier.contains(parsed_version, prereleases=True):
        raise CompatibilityError(f"{subject} does not satisfy {requirement_label}: {specifier}")


def _require_table(data: dict[str, object], key: str, *, label: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise CompatibilityError(f"{label} must define object field {key!r}")
    return cast(dict[str, object], value)


def _require_non_empty_string(data: Mapping[str, object], key: str, *, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CompatibilityError(f"{label} field {key!r} must be a non-empty string")
    return value.strip()


def _require_int(data: Mapping[str, object], key: str, *, label: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CompatibilityError(f"{label} field {key!r} must be an integer")
    return value


def _require_exact_int(
    *,
    actual: int,
    expected: int,
    subject: str,
    sdk_version: str,
) -> None:
    if actual != expected:
        raise CompatibilityError(
            f"Boxy {subject} {actual} does not satisfy "
            f"{BOXY_AGENT_DISTRIBUTION_NAME} {sdk_version} requirement {expected}"
        )
