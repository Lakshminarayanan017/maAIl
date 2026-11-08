"""User rules: the deterministic pass that runs before any agent.

A rule is the user having already answered the question. Asking a model to
second-guess an explicit instruction is expensive and rude, so rules are
evaluated first and a match ends the decision (gap E4).

Rules are ordered by ``priority`` ascending, first match wins. Matching is
plain substring and domain comparison, not a pattern language: a rule the
user cannot predict the behaviour of is a rule they will not trust, and
the correction UI that creates these rules offers only what is shown here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["RuleMatch", "ThreadFacts", "match_rules"]

_LOAD = text(
    """
    SELECT id, name, match, action
      FROM user_rules
     WHERE enabled
     ORDER BY priority, created_at
    """
)


@dataclass(frozen=True)
class ThreadFacts:
    """Everything a rule may look at. Deliberately a short list."""

    from_email: str | None
    subject: str | None
    body_text: str | None
    labels: tuple[str, ...] = ()

    @property
    def from_domain(self) -> str | None:
        if not self.from_email or "@" not in self.from_email:
            return None
        return self.from_email.rsplit("@", 1)[1].lower()


@dataclass(frozen=True)
class RuleMatch:
    rule_id: UUID
    name: str
    action: dict[str, Any]

    @property
    def skips_intelligence(self) -> bool:
        return bool(self.action.get("skip_intelligence"))


def _matches(criteria: dict[str, Any], facts: ThreadFacts) -> bool:
    """Every stated criterion must hold. An empty rule matches nothing.

    An empty-criteria rule matching everything would be a footgun that
    silently reclassifies an entire mailbox.
    """
    checks: list[bool] = []

    if value := criteria.get("from_email"):
        checks.append((facts.from_email or "").lower() == str(value).lower())
    if value := criteria.get("from_domain"):
        checks.append(facts.from_domain == str(value).lower().lstrip("@"))
    if value := criteria.get("subject_contains"):
        checks.append(str(value).lower() in (facts.subject or "").lower())
    if value := criteria.get("body_contains"):
        checks.append(str(value).lower() in (facts.body_text or "").lower())
    if value := criteria.get("has_label"):
        checks.append(str(value) in facts.labels)

    return bool(checks) and all(checks)


async def match_rules(session: AsyncSession, facts: ThreadFacts) -> RuleMatch | None:
    """The first rule that matches, or None. RLS scopes this to the tenant."""
    for row in (await session.execute(_LOAD)).all():
        if _matches(dict(row[2] or {}), facts):
            return RuleMatch(rule_id=UUID(str(row[0])), name=str(row[1]), action=dict(row[3] or {}))
    return None
