"""What an agent is, and what it must declare before it may exist.

An agent is a manifest in Git, not a class. ``agent_definitions/*.yaml`` is
procedural memory: read at deploy, never written at runtime, reviewable in
a diff. A runtime write there would be a prompt-injection vector that
survives a restart.

Four things are mandatory and the registry refuses a manifest without them:

``plane``                  what it may be given, enforced by the tool filter
``budgets``                steps, tokens and wall clock, all three
``output_schema``          an agent whose failures look like content is an
                           agent nobody can debug
``deterministic_alternative``  why code cannot do this job

That last field does the real work. Writing down why a model is necessary
is usually enough to discover that it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.mcp.catalog import Plane
from app.modules.providers.llm.base import ModelTier

__all__ = ["AgentSpec", "Budgets", "ManifestError"]


class ManifestError(Exception):
    """A manifest is missing something it may not be missing."""


@dataclass(frozen=True)
class Budgets:
    """Bounded autonomy. An unbounded loop is an unbounded bill."""

    max_steps: int
    max_tokens: int
    max_wall_clock_s: float

    def validate(self, agent_id: str) -> None:
        for name, value in (
            ("max_steps", self.max_steps),
            ("max_tokens", self.max_tokens),
            ("max_wall_clock_s", self.max_wall_clock_s),
        ):
            if value is None or value <= 0:
                raise ManifestError(f"{agent_id}: {name} must be a positive number")


@dataclass(frozen=True)
class AgentSpec:
    id: str
    version: str
    plane: Plane
    tier: ModelTier
    description: str
    prompt_version: str
    system_prompt: str
    budgets: Budgets
    output_schema: dict[str, Any]
    #: The tools this agent asked for. The plane is the ceiling; this is
    #: the agent's own statement of what it needs, and it gets nothing else.
    tools: frozenset[str] = frozenset()
    #: Why code cannot do this job. Required, and read by a human.
    deterministic_alternative: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.plane is Plane.X:
            raise ManifestError(f"{self.id}: Plane X holds no model, so no agent may claim it")
        self.budgets.validate(self.id)

        if not self.output_schema or not isinstance(self.output_schema, dict):
            raise ManifestError(f"{self.id}: an output_schema is required")
        if self.output_schema.get("type") != "object":
            raise ManifestError(f"{self.id}: output_schema must be an object schema")

        if not self.deterministic_alternative.strip():
            raise ManifestError(
                f"{self.id}: deterministic_alternative is required -- state why code "
                "cannot do this job"
            )
        if not self.system_prompt.strip():
            raise ManifestError(f"{self.id}: a system prompt is required")

    def config_hash(self) -> str:
        """Part nine of the cache key: anything else that steers the model."""
        import hashlib
        import json

        material = json.dumps(
            {"tier": self.tier.value, "budgets": self.budgets.__dict__, **self.config},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
