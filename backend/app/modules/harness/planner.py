"""The Execution Planner: decides whether a model runs at all.

Six paths out of this function, and **five of them cost nothing**. That
ordering is the whole cost model: the expensive path is last and is reached
only when every cheaper answer has been ruled out.

    user rule      -> deterministic, the user already decided
    disabled       -> skip, the feature is off
    cache hit      -> reuse, the answer exists
    bypass         -> deterministic, positive evidence it is unnecessary
    budget         -> skip, with a clear reason
    otherwise      -> invoke, at the cheapest tier that can answer

See docs/architecture/07-harness.md §2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.harness import budget as budget_manager
from app.modules.harness.cache import CacheKey, lookup

log = get_logger(__name__)


class Decision(str, Enum):
    deterministic = "deterministic"
    cached = "cached"
    skip = "skip"
    invoke = "invoke"


class Tier(str, Enum):
    """Cheapest model that can answer, not the best one available."""

    small = "small"
    large = "large"


@dataclass(frozen=True)
class IntelligenceRequest:
    user_id: UUID
    feature_id: str
    agent_id: str
    agent_version: str
    prompt_version: str
    model_id: str
    config_hash: str
    thread_id: UUID | None = None
    content_version: int = 0
    tier: Tier = Tier.small
    #: Set when a person asked for this directly. A user-initiated request
    #: is never bypassed: they can see that they asked.
    user_initiated: bool = False

    def cache_key(self) -> CacheKey:
        return CacheKey(
            user_id=self.user_id,
            thread_id=self.thread_id,
            content_version=self.content_version,
            feature_id=self.feature_id,
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            prompt_version=self.prompt_version,
            model_id=self.model_id,
            config_hash=self.config_hash,
        )


@dataclass(frozen=True)
class Plan:
    decision: Decision
    reason: str
    tier: Tier | None = None
    result_ref: dict[str, Any] | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def costs_a_model_call(self) -> bool:
        return self.decision is Decision.invoke


async def plan(
    session: AsyncSession,
    request: IntelligenceRequest,
    *,
    feature_enabled: bool = True,
    user_rule: str | None = None,
    bypass_reason: str | None = None,
) -> Plan:
    """Decide. The order of the checks is the cost model.

    ``feature_enabled``, ``user_rule`` and ``bypass_reason`` are passed in
    rather than looked up here: the planner decides, it does not own the
    feature registry or the rules engine, and keeping it that way is what
    makes it testable without a database full of settings.
    """
    if user_rule:
        # The user already answered this question. Asking a model to
        # second-guess an explicit rule is both expensive and rude.
        return Plan(Decision.deterministic, f"user_rule:{user_rule}")

    if not feature_enabled:
        return Plan(Decision.skip, "feature_disabled")

    cached = await lookup(session, request.cache_key())
    if cached is not None:
        return Plan(Decision.cached, "cache_hit", result_ref=cached)

    if bypass_reason and not request.user_initiated:
        # Asymmetric by construction: a bypass may only reduce work, never
        # hide a thread, and never applies to something a person asked for.
        return Plan(Decision.deterministic, f"bypass:{bypass_reason}")

    standing = await budget_manager.check(session, request.user_id)
    if not standing.allowed:
        return Plan(
            Decision.skip,
            "budget_exceeded",
            detail={
                "spent_micros": standing.spent_micros,
                "hard_cap_micros": standing.hard_cap_micros,
            },
        )

    return Plan(Decision.invoke, "no_cheaper_answer", tier=request.tier)
