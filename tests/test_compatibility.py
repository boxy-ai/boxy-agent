from __future__ import annotations

import pytest

from boxy_agent._version import __requires_boxy__, __version__
from boxy_agent.compatibility import (
    BoxyRuntimeProvides,
    CompatibilityError,
    require_boxy_runtime_compatible,
)


def test_requires_boxy_accepts_matching_runtime_contract() -> None:
    require_boxy_runtime_compatible(
        requires_boxy=__requires_boxy__,
        provides=BoxyRuntimeProvides(
            boxy_version="0.2.0",
            boxy_runtime_api=1,
            agent_manifest_schema=2,
            capability_catalog_schema=1,
        ),
        sdk_version=__version__,
    )


def test_requires_boxy_rejects_incompatible_boxy_version() -> None:
    with pytest.raises(CompatibilityError, match="does not satisfy"):
        require_boxy_runtime_compatible(
            requires_boxy=__requires_boxy__,
            provides=BoxyRuntimeProvides(
                boxy_version="0.3.0",
                boxy_runtime_api=1,
                agent_manifest_schema=2,
                capability_catalog_schema=1,
            ),
            sdk_version=__version__,
        )
