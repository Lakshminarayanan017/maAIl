"""Per-agent tool filtering. The phase 5 blocking gate.

> A Plane U agent **cannot discover** a Plane C or X tool -- the filtered
> schema set contains zero such entries.
> (09-execution-plan.md, phase 5)

"Cannot discover" rather than "is not allowed to call". The difference
matters: a model that can see a tool will eventually try it, and a refusal
at call time is a refusal the model can be argued out of by text it just
read. A tool that was never in the schema list cannot be argued for.
"""

from __future__ import annotations

from app.modules.mcp.catalog import Capability, Catalog, Plane, ToolSpec

__all__ = ["tools_for_agent", "visible_names"]

#: Which planes an agent on a given plane may ever see.
_VISIBLE: dict[Plane, frozenset[Plane]] = {
    # An agent that has read raw email sees only read-only tools.
    Plane.U: frozenset({Plane.U}),
    # Plane C works from validated structures and may propose.
    Plane.C: frozenset({Plane.U, Plane.C}),
    # Plane X holds no model, so no agent is ever on it.
    Plane.X: frozenset(),
}


def tools_for_agent(
    catalog: Catalog, *, agent_plane: Plane, allowlist: frozenset[str] | None = None
) -> list[ToolSpec]:
    """The only tools this agent is told exist.

    ``allowlist`` narrows further: an agent declares the tools it needs in
    its manifest, and gets those and nothing else. Plane is the ceiling;
    the allowlist is the agent's own stated requirement.
    """
    if agent_plane is Plane.X:
        raise ValueError("Plane X holds no model, so no agent runs on it")

    visible = _VISIBLE[agent_plane]
    chosen: list[ToolSpec] = []
    for name in catalog.names():
        spec = catalog.tools[name]
        if spec.plane not in visible:
            continue
        if allowlist is not None and name not in allowlist:
            continue
        # Belt and braces: even a Plane U tool is withheld from a Plane U
        # agent if it somehow carries egress. The catalog validator should
        # have caught it; this is the second place it cannot get through.
        if agent_plane is Plane.U and Capability.egress in spec.capabilities:
            continue
        chosen.append(spec)
    return chosen


def visible_names(
    catalog: Catalog, *, agent_plane: Plane, allowlist: frozenset[str] | None = None
) -> list[str]:
    return [
        spec.name for spec in tools_for_agent(catalog, agent_plane=agent_plane, allowlist=allowlist)
    ]
