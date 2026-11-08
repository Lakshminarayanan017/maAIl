"""The forbidden dependencies from AGENTS.md, asserted.

One test per rule, so a failure names the invariant it broke rather than
printing a list.
"""

from __future__ import annotations

import pytest

from tests.arch import boundaries
from tests.arch.boundaries import RULES

pytestmark = pytest.mark.arch


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.name)
def test_import_rule(rule: boundaries.Rule) -> None:
    violations = [v for v in boundaries.check_imports() if v.rule == rule.name]
    assert not violations, "\n".join([rule.reason, *map(str, violations)])


def test_owner_role_stays_off_the_request_path() -> None:
    violations = boundaries.check_owner_url()
    assert not violations, "\n".join(map(str, violations))


def test_clock_is_injected_everywhere() -> None:
    violations = boundaries.check_clock()
    assert not violations, "\n".join(map(str, violations))


def test_procedural_memory_is_never_written_at_runtime() -> None:
    violations = boundaries.check_procedural_memory_is_read_only()
    assert not violations, "\n".join(map(str, violations))


def test_the_lint_actually_catches_something(tmp_path, monkeypatch) -> None:
    """A lint nobody has seen fail is a lint nobody should trust.

    Plants a violation in a throwaway tree and asserts the scanner reports it.
    """
    scope = tmp_path / "app" / "modules" / "executor"
    scope.mkdir(parents=True)
    (scope / "bad.py").write_text("import anthropic\n", encoding="utf-8")
    monkeypatch.setattr(boundaries, "BACKEND_ROOT", tmp_path)

    violations = boundaries.check_imports()
    assert any(v.rule == "executor-has-no-model" for v in violations), (
        "the import scanner did not notice an LLM client inside Plane X"
    )
