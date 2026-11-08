"""The architecture rules, as data plus an AST scanner.

Do not tell coding agents to respect architecture — make CI reject violations.
This module is the mechanism; ``test_import_boundaries.py`` is the assertion.

It reads source with ``ast`` rather than importing it. An import-graph check
that imports the graph it is checking will happily pass on a module that
cannot be imported at all, and will execute whatever it loads.

See docs/architecture/07-harness.md §8 and AGENTS.md.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
REPO_ROOT = BACKEND_ROOT.parent

#: Any LLM SDK or framework. Plane X may not import one, at any depth.
LLM_PACKAGES: frozenset[str] = frozenset(
    {
        "anthropic",
        "openai",
        "cohere",
        "mistralai",
        "google.generativeai",
        "google.genai",
        "vertexai",
        "ollama",
        "litellm",
        "transformers",
        "torch",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langgraph",
        "llama_index",
        "instructor",
        "dspy",
    }
)


@dataclass(frozen=True)
class Rule:
    """``scope`` may not import anything matching ``forbidden``."""

    name: str
    scope: str
    forbidden: frozenset[str]
    reason: str
    #: Files inside ``scope`` this rule does not apply to.
    exempt: frozenset[str] = frozenset()
    #: Modules that match ``forbidden`` by prefix but are permitted anyway,
    #: each with its reason written in the rule.
    allowed_imports: frozenset[str] = frozenset()


RULES: tuple[Rule, ...] = (
    Rule(
        name="executor-has-no-model",
        scope="app/modules/executor",
        forbidden=LLM_PACKAGES
        | {"app.modules.agents", "app.modules.providers.llm", "app.modules.harness"},
        reason=(
            "Plane X executes approved proposals. A model inside the executor would mean a "
            "model performing a side effect, which is invariant 2."
        ),
    ),
    Rule(
        name="agents-reach-tools-only-through-mcp",
        scope="app/modules/agents",
        forbidden=frozenset({"app.modules.providers", "app.modules.mcp_servers"}),
        reason=(
            "Tools reach agents through app.modules.mcp only. This is the loose coupling, "
            "made mechanical instead of aspirational."
        ),
        # The LLM *contract* is the one exception, and a narrow one: the
        # runtime depends on the Protocol a provider implements, not on
        # any provider. The model an agent runs on is injected by the
        # caller, so importing the shape of it is dependency inversion
        # rather than a back door. Importing `providers.llm.anything_else`
        # is still a build failure.
        allowed_imports=frozenset({"app.modules.providers.llm.base"}),
    ),
    Rule(
        name="mcp-servers-cannot-act-or-reason",
        scope="app/modules/mcp_servers",
        forbidden=frozenset({"app.modules.executor", "app.modules.agents"}),
        reason=(
            "A server that could call the executor would route around approval; one that "
            "could call an agent would make the tool graph recursive."
        ),
    ),
    Rule(
        name="core-does-not-depend-on-modules",
        scope="app/core",
        forbidden=frozenset({"app.modules", "app.api"}),
        reason="core is the bottom of the stack; a cycle through it voids every other rule.",
    ),
    Rule(
        name="ingest-is-deterministic",
        scope="app/modules/ingest",
        forbidden=LLM_PACKAGES | {"app.modules.agents", "app.modules.harness"},
        reason="Tier 0 is a zero-LLM zone. See 07-harness.md §6.",
    ),
    Rule(
        name="sync-is-deterministic",
        scope="app/modules/sync",
        forbidden=LLM_PACKAGES | {"app.modules.agents"},
        reason="Sync is a zero-LLM zone.",
    ),
    Rule(
        name="features-gating-is-deterministic",
        scope="app/modules/features",
        forbidden=LLM_PACKAGES | {"app.modules.agents"},
        reason="Feature gating decides whether work happens; it runs before any model.",
    ),
    Rule(
        name="threads-is-deterministic",
        scope="app/modules/threads",
        forbidden=LLM_PACKAGES | {"app.modules.agents"},
        reason="Thread reconstruction is a zero-LLM zone.",
    ),
    Rule(
        name="approval-validation-is-deterministic",
        scope="app/modules/approvals",
        forbidden=LLM_PACKAGES,
        reason="Approval validation is a zero-LLM zone.",
    ),
    Rule(
        name="auth-is-deterministic",
        scope="app/modules/accounts",
        forbidden=LLM_PACKAGES | {"app.modules.agents", "app.modules.harness"},
        reason=(
            "Auth, token refresh and account lifecycle are a zero-LLM zone. A model "
            "deciding whether a credential is valid is the wrong problem."
        ),
    ),
    Rule(
        name="the-http-layer-never-calls-a-model",
        scope="app/api",
        forbidden=LLM_PACKAGES,
        reason=(
            "A request handler that calls a model holds the connection open for the "
            "length of a generation. Handlers enqueue; workers run agents."
        ),
    ),
)

#: Only these may touch the owner role. Everything on a request path is
#: connected as the non-owner application role, which is what arms RLS.
OWNER_URL_ALLOWED: frozenset[str] = frozenset(
    {
        "app/core/config.py",
        "app/database/seed.py",
        "app/database/audit.py",
        # Maintenance: rewrites every tenant's rows, so it is cross-tenant
        # by nature and runs as the owner, like the seed and the audit.
        "app/modules/ingest/backfill.py",
    }
)

#: Procedural memory. A runtime write here is a prompt-injection vector that
#: survives a restart, not a feature.
READ_ONLY_DIRS: tuple[str, ...] = (
    "agent_definitions",
    "procedures",
    "prompts",
    "tool_contracts",
)

#: Only the clock may read the wall clock.
CLOCK_ALLOWED: frozenset[str] = frozenset({"app/core/clock.py"})

CLOCK_CALLS: frozenset[str] = frozenset(
    {"datetime.now", "datetime.utcnow", "date.today", "time.time", "time.monotonic"}
)


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.rule}]  {self.detail}"


def python_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def relative(path: Path) -> str:
    return path.relative_to(BACKEND_ROOT).as_posix()


def imported_modules(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """Every absolute module name this file imports, with its line number."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — stays inside its own package
                continue
            if node.module:
                yield node.module, node.lineno
                for alias in node.names:
                    yield f"{node.module}.{alias.name}", node.lineno


def _matches(module: str, forbidden: frozenset[str]) -> str | None:
    for bad in forbidden:
        if module == bad or module.startswith(bad + "."):
            return bad
    return None


def check_imports() -> list[Violation]:
    violations: list[Violation] = []
    for rule in RULES:
        scope = BACKEND_ROOT / rule.scope
        if not scope.exists():
            continue
        for path in python_files(scope):
            rel = relative(path)
            if rel in rule.exempt:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module, line in imported_modules(tree):
                if _matches(module, rule.allowed_imports):
                    continue
                hit = _matches(module, rule.forbidden)
                if hit:
                    violations.append(
                        Violation(rule.name, rel, line, f"imports {module!r} (forbidden: {hit})")
                    )
    return violations


def check_owner_url() -> list[Violation]:
    """Nothing on a request path may reach for the owner connection."""
    violations: list[Violation] = []
    for path in python_files(APP_ROOT):
        rel = relative(path)
        if rel in OWNER_URL_ALLOWED:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "owner_database_url" in line:
                violations.append(
                    Violation(
                        "owner-role-off-the-request-path",
                        rel,
                        lineno,
                        "uses owner_database_url; the application connects as the non-owner "
                        "role, which is what makes RLS inescapable",
                    )
                )
    return violations


def check_clock() -> list[Violation]:
    """Only ``app/core/clock.py`` reads the wall clock.

    Half of ``deadlines`` is relative-date resolution. A suite whose answers
    change on Friday is not a suite.
    """
    violations: list[Violation] = []
    for path in python_files(APP_ROOT):
        rel = relative(path)
        if rel in CLOCK_ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            if name and name in CLOCK_CALLS:
                violations.append(
                    Violation(
                        "clock-is-injected",
                        rel,
                        node.lineno,
                        f"calls {name}(); take a Clock dependency instead "
                        "(app.core.clock.get_clock)",
                    )
                )
    return violations


def check_procedural_memory_is_read_only() -> list[Violation]:
    """No runtime write to procedural memory.

    Catches a path built from one of the read-only directory names being handed
    to something that writes. Git is the store; a restart must not be able to
    inherit a poisoned procedure.
    """
    writers = {"open", "write_text", "write_bytes", "mkdir", "unlink", "rmtree", "replace"}
    violations: list[Violation] = []
    for path in python_files(APP_ROOT):
        rel = relative(path)
        source = path.read_text(encoding="utf-8")
        if not any(d in source for d in READ_ONLY_DIRS):
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            if not name:
                continue
            leaf = name.rsplit(".", 1)[-1]
            if leaf not in writers:
                continue
            literals = " ".join(
                a.value
                for a in ast.walk(node)
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            )
            hit = next((d for d in READ_ONLY_DIRS if d in literals), None)
            if hit:
                violations.append(
                    Violation(
                        "procedural-memory-is-read-only",
                        rel,
                        node.lineno,
                        f"{leaf}() targets {hit}/ — procedural memory is written through Git, "
                        "never at runtime",
                    )
                )
    return violations


def _dotted(node: ast.expr) -> str | None:
    """``datetime.now`` from ``datetime.datetime.now`` — the last two parts."""
    parts: list[str] = []
    current: ast.expr | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif current is not None:
        return None
    if not parts:
        return None
    parts.reverse()
    return ".".join(parts[-2:]) if len(parts) > 1 else parts[0]


def check_all() -> list[Violation]:
    return [
        *check_imports(),
        *check_owner_url(),
        *check_clock(),
        *check_procedural_memory_is_read_only(),
    ]


def main() -> int:
    import sys

    violations = check_all()
    for violation in violations:
        sys.stderr.write(f"{violation}\n")
    if violations:
        sys.stderr.write(f"\n{len(violations)} architecture violation(s)\n")
        return 1
    sys.stdout.write(f"architecture: {len(RULES)} import rules + 3 audits, clean\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
