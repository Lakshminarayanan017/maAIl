"""Build the MCP host and the agent registry at startup, or fail.

Called once from the application lifespan and once from the worker. The
order is the point: servers, then catalog, then pins, then agents. A
process that gets past this has a tool surface nobody has changed since it
was reviewed, and no agent that names a tool its plane forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.agents.runtime.registry import load_registry, validate_registry
from app.modules.agents.runtime.spec import AgentSpec, ManifestError
from app.modules.mcp.client_manager import ClientHost, host
from app.modules.mcp_servers import mail, memory, search

log = get_logger(__name__)


@dataclass
class Runtime:
    host: ClientHost
    agents: dict[str, AgentSpec]


_runtime: Runtime | None = None


def build(*, strict: bool | None = None) -> Runtime:
    """Wire everything together. ``strict`` defaults to on outside tests."""
    global _runtime

    enforce = settings.env != "test" if strict is None else strict

    client = ClientHost()
    client.register(mail.server)
    client.register(search.server)
    client.register(memory.server)
    catalog = client.discover(strict=enforce)

    agents = load_registry()
    problems = validate_registry(agents, catalog)
    if problems:
        message = "; ".join(problems)
        if enforce:
            # Startup failure, not a warning. An agent that can see a tool
            # its plane forbids is the thing the planes exist to prevent.
            raise ManifestError(message)
        log.warning("agents.registry_problems", detail=message)

    _runtime = Runtime(host=client, agents=agents)

    # Keep the module-level singleton in step, so callers that imported
    # `host` directly are not looking at an empty catalog.
    host.__dict__.update(client.__dict__)

    log.info("runtime.ready", tools=len(catalog.tools), agents=len(agents))
    return _runtime


def runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("the agent runtime has not been built; call bootstrap.build()")
    return _runtime
