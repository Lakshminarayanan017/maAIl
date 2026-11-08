"""The in-process transport. v1 runs every MCP server inside the API.

MCP is a contract boundary here, not a deployment choice. The servers are
Python objects called directly; there is no subprocess, no socket and no
serialisation cost. What makes it MCP is that tools are declared with JSON
Schema, filtered by plane, pinned by hash, and invoked through one
lifecycle -- all of which survive a move to stdio or Streamable HTTP later.

Switching transport is a config flag, not a rewrite, which is the point of
writing the boundary now rather than the deployment.

See docs/architecture/06-mcp.md §1.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.mcp.catalog import ToolSpec

#: A tool implementation: structured args in, JSON-serialisable result out.
Handler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class InProcessServer:
    """One MCP server: a name, its tools, and their handlers."""

    name: str
    _handlers: dict[str, Handler] = field(default_factory=dict)
    _specs: dict[str, ToolSpec] = field(default_factory=dict)

    def tool(self, spec: ToolSpec) -> Callable[[Handler], Handler]:
        def register(handler: Handler) -> Handler:
            spec.validate()
            self._specs[spec.name] = spec
            self._handlers[spec.name] = handler
            return handler

        return register

    def specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        handler = self._handlers.get(name)
        if handler is None:
            raise KeyError(f"{self.name} has no tool {name}")
        return await handler(args)
