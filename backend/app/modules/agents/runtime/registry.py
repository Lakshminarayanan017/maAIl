"""Load the agent manifests from Git and refuse the invalid ones.

Procedural memory: ``agent_definitions/*.yaml`` is read at startup and
never written at runtime. Validation happens here, at load, so a bad
manifest stops the process rather than failing the first time someone
triggers that agent in production.

``validate_registry`` is the function CI calls. It checks each manifest
against ``AgentSpec.validate`` and then checks the pair of agent and
catalog: an agent may not name a tool that does not exist, and may not name
one its plane forbids.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger
from app.modules.agents.runtime.spec import AgentSpec, Budgets, ManifestError
from app.modules.mcp.catalog import Catalog, Plane
from app.modules.mcp.filter import visible_names
from app.modules.providers.llm.base import ModelTier

log = get_logger(__name__)

DEFINITIONS_DIR = Path(__file__).resolve().parents[5] / "agent_definitions"
PROMPTS_DIR = Path(__file__).resolve().parents[5] / "prompts"


def _read_prompt(agent_id: str, prompt_version: str) -> str:
    path = PROMPTS_DIR / agent_id / f"{prompt_version}.md"
    if not path.exists():
        raise ManifestError(f"{agent_id}: no prompt at prompts/{agent_id}/{prompt_version}.md")
    return path.read_text(encoding="utf-8").strip()


def parse_manifest(data: dict[str, Any], *, source: str = "<inline>") -> AgentSpec:
    required = ("id", "version", "plane", "tier", "prompt_version", "budgets", "output_schema")
    missing = [key for key in required if key not in data]
    if missing:
        raise ManifestError(f"{source}: missing {', '.join(missing)}")

    agent_id = str(data["id"])
    budgets_raw = data["budgets"] or {}

    spec = AgentSpec(
        id=agent_id,
        version=str(data["version"]),
        plane=Plane(str(data["plane"])),
        tier=ModelTier(str(data["tier"])),
        description=str(data.get("description", "")),
        prompt_version=str(data["prompt_version"]),
        system_prompt=_read_prompt(agent_id, str(data["prompt_version"])),
        budgets=Budgets(
            max_steps=int(budgets_raw.get("max_steps", 0)),
            max_tokens=int(budgets_raw.get("max_tokens", 0)),
            max_wall_clock_s=float(budgets_raw.get("max_wall_clock_s", 0)),
        ),
        output_schema=dict(data["output_schema"]),
        tools=frozenset(str(name) for name in (data.get("tools") or [])),
        deterministic_alternative=str(data.get("deterministic_alternative", "")),
        config=dict(data.get("config") or {}),
    )
    spec.validate()
    return spec


def load_registry(directory: Path | None = None) -> dict[str, AgentSpec]:
    """Every manifest in Git, validated. Raises on the first bad one."""
    root = directory or DEFINITIONS_DIR
    registry: dict[str, AgentSpec] = {}

    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        spec = parse_manifest(data, source=path.name)
        if spec.id in registry:
            raise ManifestError(f"{path.name}: duplicate agent id {spec.id}")
        registry[spec.id] = spec

    log.info("agents.loaded", count=len(registry), ids=sorted(registry))
    return registry


def validate_registry(registry: dict[str, AgentSpec], catalog: Catalog) -> list[str]:
    """Check each agent against the catalog. Returns the problems.

    Two things the manifest cannot check on its own: whether the tools it
    names exist, and whether its plane permits them. Both are startup
    failures rather than runtime surprises.
    """
    problems: list[str] = []

    for agent_id, spec in sorted(registry.items()):
        allowed = set(visible_names(catalog, agent_plane=spec.plane))
        for tool in sorted(spec.tools):
            if tool not in catalog.tools:
                problems.append(f"{agent_id}: names a tool that does not exist: {tool}")
            elif tool not in allowed:
                actual = catalog.tools[tool].plane.value
                problems.append(
                    f"{agent_id}: is Plane {spec.plane.value} but names {tool}, "
                    f"which is Plane {actual}"
                )

    return problems
