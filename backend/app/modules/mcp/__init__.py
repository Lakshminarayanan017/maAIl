"""MCP client host -- the contract boundary.

In v1 the transport is in-process; stdio and Streamable HTTP are a config
flag, not a rewrite. Schema pinning fails closed on a mismatch, and Maail
owns the plane and capability metadata, because a server that declares its
own permissions grants itself permissions.
"""

from app.modules.mcp.catalog import Capability, Catalog, Plane, SchemaDrift, ToolSpec
from app.modules.mcp.client_manager import ClientHost, host

__all__ = [
    "Capability",
    "Catalog",
    "ClientHost",
    "Plane",
    "SchemaDrift",
    "ToolSpec",
    "host",
]
