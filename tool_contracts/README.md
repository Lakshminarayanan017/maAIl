# tool_contracts — pinned MCP tool schemas

One pinned schema per MCP tool, with its hash. Discovery compares the live schema against
the pin and **fails closed** on a mismatch, which is the defence against a server silently
changing a tool's shape or description under us.

Maail owns the plane, capability and egress metadata here. A server that declares its own
permissions grants itself permissions.

See [docs/architecture/06-mcp.md](../docs/architecture/06-mcp.md) §3. Populated in phase 5.
