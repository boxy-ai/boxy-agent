import boxy_agent


def test_import() -> None:
    assert boxy_agent.__version__ == "0.2.0a6"
    assert boxy_agent.__requires_boxy__ == {
        "boxy_version": ">=0.2.0,<0.3.0",
        "boxy_runtime_api": ">=1,<2",
        "agent_manifest_schema": 2,
        "capability_catalog_schema": 1,
    }
