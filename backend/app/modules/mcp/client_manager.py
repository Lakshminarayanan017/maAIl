"""The MCP client host: discovery, pinning, filtering, invocation.

One object owns the whole tool surface. Agents never import a server and
never import a provider; they ask this for the tools they are allowed to
see, and call back through ``invoke``. That indirection is what the
import-boundary test in CI enforces, and it is the only reason the planes
hold at runtime rather than by convention.

Startup order matters and is fixed:

1. register every server
2. build the catalog, validating each tool's plane against its capabilities
3. verify every schema against its pin, **failing closed** on drift

A process that gets past step 3 is a process where no tool has changed
shape since someone reviewed it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.modules.mcp.catalog import Catalog, Plane, ToolSpec, load_pins, verify_pins
from app.modules.mcp.filter import tools_for_agent
from app.modules.mcp.transports.inprocess import InProcessServer

log = get_logger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned, and a digest of it for the trace.

    The digest, not the content, is what reaches ``agent_steps``: a trace
    holding raw tool output is a second copy of the mailbox in a table
    nobody thinks of as sensitive (gap D8).
    """

    value: Any
    digest: str
    byte_size: int
    latency_ms: int


class ClientHost:
    def __init__(self) -> None:
        self._servers: dict[str, InProcessServer] = {}
        self.catalog = Catalog()
        self._ready = False

    # -- startup -----------------------------------------------------------
    def register(self, server: InProcessServer) -> None:
        if self._ready:
            raise RuntimeError("register servers before discovery, not after")
        self._servers[server.name] = server

    def discover(self, *, strict: bool = True) -> Catalog:
        """Build the catalog and check it against the pins.

        Raises on drift when ``strict``, which is how startup is supposed
        to fail rather than serving an agent a tool nobody reviewed.
        """
        self.catalog = Catalog(pins=load_pins())
        for server in self._servers.values():
            for spec in server.specs():
                self.catalog.register(spec)

        verify_pins(self.catalog, strict=strict)
        self._ready = True
        log.info(
            "mcp.discovered",
            servers=sorted(self._servers),
            tools=len(self.catalog.tools),
        )
        return self.catalog

    # -- use ---------------------------------------------------------------
    def tools_for(
        self, *, agent_plane: Plane, allowlist: frozenset[str] | None = None
    ) -> list[ToolSpec]:
        if not self._ready:
            raise RuntimeError("discover() has not run; the catalog is not verified")
        return tools_for_agent(self.catalog, agent_plane=agent_plane, allowlist=allowlist)

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        *,
        agent_plane: Plane,
        allowlist: frozenset[str] | None = None,
    ) -> ToolResult:
        """Call a tool, re-checking that this agent may see it.

        The filter already withheld it from the schema list. This checks
        again at the call, because "the model should not know about it" and
        "the model must not be able to run it" are different guarantees and
        only the second one survives a prompt injection that guesses a name.
        """
        permitted = {
            spec.name for spec in self.tools_for(agent_plane=agent_plane, allowlist=allowlist)
        }
        if name not in permitted:
            raise PermissionError(f"a Plane {agent_plane.value} agent may not call {name}")

        spec = self.catalog.tools[name]
        server = self._servers.get(spec.server)
        if server is None:
            raise KeyError(f"no server {spec.server} for tool {name}")

        started = time.perf_counter()
        value = await server.call(name, args)
        latency_ms = int((time.perf_counter() - started) * 1000)

        encoded = json.dumps(value, default=str, sort_keys=True).encode("utf-8")
        return ToolResult(
            value=value,
            digest=hashlib.sha256(encoded).hexdigest(),
            byte_size=len(encoded),
            latency_ms=latency_ms,
        )


#: The process-wide host. Built at startup, read everywhere.
host = ClientHost()
