"""The tool catalog: what exists, what plane it belongs to, and its pin.

Two properties make this a security boundary rather than a registry.

**Maail owns the metadata.** A server describes its tools; it does not get
to say what they are allowed to do. Plane, capabilities and egress are
assigned here, from a table in this repository, because a server that
declares its own permissions grants itself permissions.

**Schemas are pinned.** Discovery hashes each tool's schema and compares it
against the pin in ``tool_contracts/``. A mismatch **fails closed**: the
tool is withdrawn and startup fails. This is the defence against a server
quietly changing a tool's shape or its description under a running agent --
the rug-pull, and the description half of tool poisoning.

See docs/architecture/06-mcp.md §3.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "tool_contracts"


class Plane(str, Enum):
    """Where a tool may be used, not where it happens to live.

    U  may be given to an agent that has seen untrusted text
    C  only for an agent working from validated structures
    X  never given to any agent; the executor calls it directly
    """

    U = "U"
    C = "C"
    X = "X"


class Capability(str, Enum):
    read = "read"
    propose = "propose"
    execute = "execute"
    #: Reaches outside Maail. A Plane U tool may never hold this.
    egress = "egress"


class SchemaDrift(Exception):
    """A tool's schema no longer matches its pin. Fails closed."""


class PlaneViolation(Exception):
    """A tool's declared plane contradicts what it can do."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    server: str
    description: str
    input_schema: dict[str, Any]
    plane: Plane
    capabilities: frozenset[Capability]
    #: Set only for tools Maail itself owns. An external server's tools are
    #: pinned by hash and nothing else is assumed about them.
    owned: bool = True

    def schema_hash(self) -> str:
        """Covers the description too.

        A tool whose description changes is a tool whose instructions to
        the model changed, which is the whole of description-based tool
        poisoning. Hashing only the parameters would miss it.
        """
        material = json.dumps(
            {
                "name": self.name,
                "description": self.description,
                "input_schema": self.input_schema,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        """The invariants a tool must satisfy to exist at all."""
        if self.plane is Plane.U:
            forbidden = self.capabilities & {
                Capability.execute,
                Capability.propose,
                Capability.egress,
            }
            if forbidden:
                raise PlaneViolation(
                    f"{self.name} is Plane U but claims "
                    f"{sorted(c.value for c in forbidden)}; a component that reads "
                    "untrusted text must hold nothing that acts"
                )
        if self.plane is Plane.C and Capability.execute in self.capabilities:
            raise PlaneViolation(
                f"{self.name} is Plane C but claims execute; Plane C proposes, Plane X executes"
            )


@dataclass
class Catalog:
    tools: dict[str, ToolSpec] = field(default_factory=dict)
    pins: dict[str, str] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        spec.validate()
        if spec.name in self.tools:
            raise ValueError(f"duplicate tool name {spec.name}")
        self.tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def names(self) -> list[str]:
        return sorted(self.tools)


def load_pins(directory: Path | None = None) -> dict[str, str]:
    """Pinned schema hashes from Git. Absent file means no tools are pinned."""
    path = (directory or CONTRACTS_DIR) / "pins.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchemaDrift(f"{path} is not valid JSON: {exc}") from exc
    return {str(k): str(v) for k, v in data.items()}


def verify_pins(catalog: Catalog, *, strict: bool = True) -> list[str]:
    """Compare every tool against its pin.

    ``strict`` is what CI and production run with: an unpinned or drifted
    tool stops the process. Development can pass False to see the whole
    list at once rather than the first failure.
    """
    problems: list[str] = []
    for name, spec in sorted(catalog.tools.items()):
        actual = spec.schema_hash()
        pinned = catalog.pins.get(name)
        if pinned is None:
            problems.append(f"{name}: not pinned in tool_contracts/pins.json")
        elif pinned != actual:
            problems.append(f"{name}: schema drift (pinned {pinned[:12]}, got {actual[:12]})")

    if problems and strict:
        # Fail closed. A tool whose shape has changed under a running agent
        # is a tool nobody reviewed.
        raise SchemaDrift("; ".join(problems))
    for problem in problems:
        log.warning("mcp.pin_problem", detail=problem)
    return problems


def write_pins(catalog: Catalog, directory: Path | None = None) -> Path:
    """Regenerate the pin file. Run deliberately, and review the diff."""
    path = (directory or CONTRACTS_DIR) / "pins.json"
    payload = {name: spec.schema_hash() for name, spec in sorted(catalog.tools.items())}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
