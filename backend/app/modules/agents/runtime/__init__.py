"""The agent runtime: manifests, planes, the bounded loop, traces.

Tools reach agents only through ``app.modules.mcp``. Nothing here imports
a provider or a server, and CI fails the build if it ever does -- that is
the loose coupling, made mechanical rather than aspirational.
"""

from app.modules.agents.runtime.loop import RunOutcome, RunResult, run_agent
from app.modules.agents.runtime.registry import load_registry, validate_registry
from app.modules.agents.runtime.spec import AgentSpec, Budgets, ManifestError

__all__ = [
    "AgentSpec",
    "Budgets",
    "ManifestError",
    "RunOutcome",
    "RunResult",
    "load_registry",
    "run_agent",
    "validate_registry",
]
