from __future__ import annotations

from functools import lru_cache

from boxy_agent.capabilities import CapabilityCatalog, load_packaged_capability_catalog
from boxy_agent.models import DataQueryDescriptor, ToolDescriptor

DEFAULT_DATA_QUERY_NAME = "whatsapp.chat_context"
DEFAULT_BOXY_TOOL_NAME = "whatsapp.send_message"
DEFAULT_BUILTIN_TOOL_NAME = "web_search"


@lru_cache(maxsize=1)
def default_capability_catalog() -> CapabilityCatalog:
    return load_packaged_capability_catalog()


@lru_cache(maxsize=1)
def empty_capability_catalog() -> CapabilityCatalog:
    return CapabilityCatalog(data_queries={}, boxy_tools={}, builtin_tools={})


def data_query_registry() -> dict[str, DataQueryDescriptor]:
    return dict(default_capability_catalog().data_queries)


def boxy_tool_registry() -> dict[str, ToolDescriptor]:
    return dict(default_capability_catalog().boxy_tools)


def builtin_tool_registry() -> dict[str, ToolDescriptor]:
    return dict(default_capability_catalog().builtin_tools)
