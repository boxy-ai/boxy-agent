from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from boxy_agent.capabilities import CapabilityCatalog, load_capability_catalog
from boxy_agent.models import DataQueryDescriptor, ToolDescriptor

DEFAULT_CAPABILITY_CATALOG_PATH = Path(__file__).with_name("default_capability_catalog.toml")


@lru_cache(maxsize=1)
def default_capability_catalog() -> CapabilityCatalog:
    return load_capability_catalog(DEFAULT_CAPABILITY_CATALOG_PATH)


@lru_cache(maxsize=1)
def empty_capability_catalog() -> CapabilityCatalog:
    return CapabilityCatalog(data_queries={}, boxy_tools={}, builtin_tools={})


def data_query_registry() -> dict[str, DataQueryDescriptor]:
    return dict(default_capability_catalog().data_queries)


def boxy_tool_registry() -> dict[str, ToolDescriptor]:
    return dict(default_capability_catalog().boxy_tools)


def builtin_tool_registry() -> dict[str, ToolDescriptor]:
    return dict(default_capability_catalog().builtin_tools)
