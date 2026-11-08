"""Triage: the economic keystone, and the service that drives it.

Every new thread passes through here, and what Triage decides is what each
expensive agent downstream is allowed to look at. So the order of the
cheap checks before the model matters more than the model does:

    user rule     the user already decided
    bypass        positive evidence it is unnecessary, asymmetric
    cache         this content version has been triaged
    budget        the planner's last gate
    model         only now

Whatever the path, the thread ends with a row in ``thread_intelligence``
and a snapshot in ``thread_intelligence_versions``. A thread that was
bypassed is still classified and still visible; the audit trail records
that no model saw it and why.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.logging import get_logger
from app.database.models.thread import EmailMessage, EmailThread
from app.modules.agents.runtime import RunOutcome, run_agent
from app.modules.agents.runtime.spec import AgentSpec
from app.modules.features import service as features
from app.modules.harness import budget as budget_manager
from app.modules.harness import cache as result_cache
from app.modules.harness.context_builder import build_thread_context
from app.modules.harness.planner import Decision, IntelligenceRequest, Tier, plan
from app.modules.mcp.client_manager import ClientHost
from app.modules.providers.llm.base import LLMProvider
from app.modules.rules import ThreadFacts, match_rules
from app.modules.rules.bypass import evaluate_bypass

log = get_logger(__name__)

AGENT_ID = "triage"
FEATURE_ID = "triage"

#: Bumped when the deterministic half of triage changes in a way that
#: should invalidate stored results (gap C7).
PIPELINE_VERSION = "triage-1"

#: Which settings toggle owns each of this agent's outputs. Triage
#: itself is ALWAYS_ON in the registry -- what the user controls is
#: what it is allowed to write.
OUTPUT_FEATURES = {
    "priority": "priority_detection",
    "category": "smart_categorization",
    "technical": "technical_detection",
}

#: Which toggle owns each specialist Triage can route to. Routing to a
#: disabled agent would leave its capability 'pending' for ever --
#: queued for something that will refuse to run.
ROUTE_FEATURES = {
    "summarizer": "instant_summaries",
    "deadline": "deadline_detection",
    "action_items": "action_extraction",
    "developer": "technical_detection",
    "opportunity": "opportunity_discovery",
}

VALID_CATEGORIES = frozenset(
    {
        "technical",
        "opportunity",
        "academic",
        "administrative",
        "personal",
        "promotional",
        "notification",
        "other",
    }
)


@dataclass
class TriageOutcome:
    thread_id: UUID
    category: str
    priority: int
    priority_reason: str
    needs_reply: bool
    is_technical: bool
    route_to: list[str]
    #: How this was decided: rule, bypass, cache or agent. Recorded so the
    #: bypass rate can be measured rather than guessed.
    source: str
    run_id: UUID | None = None
    cost_micros: int = 0


_UPSERT = text(
    """
    INSERT INTO thread_intelligence
        (thread_id, user_id, category, category_source, priority, priority_reason,
         priority_computed_at, needs_reply, is_technical, routed_agents,
         status_summary, status_deadline, status_actions,
         computed_from_content_version, pipeline_version, updated_at)
    VALUES
        (:thread_id, :user_id, CAST(:category AS thread_category), :category_source,
         :priority, :priority_reason, now(), :needs_reply, :is_technical,
         CAST(:routed AS text[]),
         CAST(:status_summary AS capability_status),
         CAST(:status_deadline AS capability_status),
         CAST(:status_actions AS capability_status),
         :content_version, :pipeline_version, now())
    ON CONFLICT (thread_id) DO UPDATE SET
        category = excluded.category,
        category_source = excluded.category_source,
        priority = excluded.priority,
        priority_reason = excluded.priority_reason,
        priority_computed_at = excluded.priority_computed_at,
        needs_reply = excluded.needs_reply,
        is_technical = excluded.is_technical,
        routed_agents = excluded.routed_agents,
        status_summary = excluded.status_summary,
        status_deadline = excluded.status_deadline,
        status_actions = excluded.status_actions,
        computed_from_content_version = excluded.computed_from_content_version,
        pipeline_version = excluded.pipeline_version,
        updated_at = now()
    """
)

_SNAPSHOT = text(
    """
    INSERT INTO thread_intelligence_versions
        (thread_id, user_id, snapshot, content_version, pipeline_version, agent_run_id)
    VALUES (:thread_id, :user_id, CAST(:snapshot AS jsonb), :content_version,
            :pipeline_version, :run_id)
    """
)

_SENDER_HISTORY = text(
    """
    SELECT count(DISTINCT m.thread_id),
           count(DISTINCT m.thread_id) FILTER (
             WHERE EXISTS (SELECT 1 FROM email_messages r
                            WHERE r.thread_id = m.thread_id AND r.is_from_user)
           )
      FROM email_messages m
     WHERE m.from_email = :email AND m.deleted_at IS NULL
    """
)


async def triage_thread(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    thread_id: UUID,
    user_initiated: bool = False,
) -> TriageOutcome | None:
    """Classify one thread. Returns None when the thread is gone."""
    thread = await session.get(EmailThread, thread_id)
    if thread is None or thread.merged_into_thread_id is not None:
        return None

    # One agent, three toggleable outputs.
    #
    # Priority detection, Smart categorization and Technical email
    # detection are three separate toggles in the settings screen and one
    # model call here. Splitting them into three agents to make the
    # mapping tidy would have tripled the cost of the most-run agent in
    # the system to honour a setting, so instead: the call happens if any
    # of the three is wanted, and each output is written only if its own
    # toggle is on. A toggle is a promise about what Maail does to your
    # mail, not about which process runs.
    wanted = await _wanted_outputs(session, user_id)
    if not any(wanted.values()):
        await _mark_skipped(session, user_id=user_id, thread=thread, reason="disabled")
        log.info("triage.all_outputs_disabled", thread_id=str(thread_id))
        return None

    newest = (
        await session.execute(
            select(EmailMessage)
            .where(EmailMessage.thread_id == thread_id, EmailMessage.deleted_at.is_(None))
            .order_by(EmailMessage.sent_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if newest is None:
        return None

    facts = ThreadFacts(
        from_email=newest.from_email,
        subject=thread.subject,
        body_text=newest.body_text_stripped or newest.snippet,
        labels=tuple(thread.provider_labels),
    )

    # 1. The user already decided.
    rule = await match_rules(session, facts)
    if rule is not None:
        outcome = _from_rule(thread, rule.action, rule.name)
        await _store(session, user_id=user_id, thread=thread, outcome=outcome, wanted=wanted)
        return outcome

    # 2. Positive evidence that no model is needed.
    history = (
        await session.execute(_SENDER_HISTORY, {"email": (newest.from_email or "").lower()})
    ).one()
    bypass = evaluate_bypass(
        sender=newest.from_email,
        provider_labels=tuple(thread.provider_labels),
        body_text=facts.body_text,
        sender_known=int(history[0] or 0) > 1,
        sender_reply_count=int(history[1] or 0),
        user_initiated=user_initiated,
    )
    if bypass.bypassed:
        outcome = TriageOutcome(
            thread_id=thread_id,
            category=bypass.category or "other",
            priority=bypass.priority if bypass.priority is not None else 1,
            priority_reason=bypass.explanation,
            needs_reply=False,
            is_technical=False,
            route_to=[],
            source=f"bypass:{bypass.reason}",
        )
        await _store(session, user_id=user_id, thread=thread, outcome=outcome, wanted=wanted)
        log.info("triage.bypassed", thread_id=str(thread_id), reason=bypass.reason)
        return outcome

    # 3 and 4. Cache, then budget.
    request = IntelligenceRequest(
        user_id=user_id,
        feature_id=FEATURE_ID,
        agent_id=spec.id,
        agent_version=spec.version,
        prompt_version=spec.prompt_version,
        model_id=provider.model_id,
        config_hash=spec.config_hash(),
        thread_id=thread_id,
        content_version=thread.content_version,
        tier=Tier.small,
        user_initiated=user_initiated,
    )
    decision = await plan(
        session,
        request,
        # Any one of the three is reason enough to run; none of them
        # is reason to skip.
        feature_enabled=any(wanted.values()),
    )

    if decision.decision is Decision.cached:
        log.info("triage.cache_hit", thread_id=str(thread_id))
        return None
    if decision.decision is Decision.skip:
        # Honest about why nothing happened, rather than silently blank.
        await _mark_skipped(session, user_id=user_id, thread=thread, reason=decision.reason)
        return None

    # 5. The model.
    context = await build_thread_context(
        session,
        thread_id=thread_id,
        system=spec.system_prompt,
        question=(
            f"user_id: {user_id}\nthread_id: {thread_id}\n"
            f"sender: {newest.from_email}\nClassify this thread."
        ),
        max_tokens=spec.budgets.max_tokens // 2,
    )

    result = await run_agent(
        session,
        spec=spec,
        provider=provider,
        host=host,
        user_id=user_id,
        user_prompt=context.render(),
        trigger="thread_ingested" if not user_initiated else "user_requested",
        subject_type="thread",
        subject_id=thread_id,
    )
    await budget_manager.spend(session, user_id, result.cost_micros)

    if result.outcome is not RunOutcome.succeeded or result.output is None:
        await _mark_failed(session, user_id=user_id, thread=thread, run_id=result.run_id)
        return None

    outcome = _from_output(thread_id, result.output, run_id=result.run_id)
    outcome.route_to = await _allowed_routes(session, user_id, outcome.route_to)
    outcome.cost_micros = result.cost_micros
    await _store(session, user_id=user_id, thread=thread, outcome=outcome, wanted=wanted)
    await result_cache.record(
        session, request.cache_key(), {"kind": "thread_intelligence", "thread_id": str(thread_id)}
    )
    return outcome


# ---------------------------------------------------------------------------
def _from_rule(thread: EmailThread, action: dict[str, Any], name: str) -> TriageOutcome:
    category = str(action.get("set_category") or "other")
    return TriageOutcome(
        thread_id=thread.id,
        category=category if category in VALID_CATEGORIES else "other",
        priority=int(action.get("set_priority", 1)),
        priority_reason=f"Your rule: {name}",
        needs_reply=False,
        is_technical=category == "technical",
        route_to=[],
        source="user_rule",
    )


def _from_output(thread_id: UUID, output: dict[str, Any], *, run_id: UUID) -> TriageOutcome:
    category = str(output.get("category", "other"))
    priority = output.get("priority", 1)
    return TriageOutcome(
        thread_id=thread_id,
        category=category if category in VALID_CATEGORIES else "other",
        priority=max(0, min(3, int(priority) if isinstance(priority, (int, float)) else 1)),
        priority_reason=str(output.get("priority_reason", ""))[:200],
        needs_reply=bool(output.get("needs_reply", False)),
        is_technical=bool(output.get("is_technical", False)),
        route_to=[str(name) for name in (output.get("route_to") or [])][:5],
        source="agent",
        run_id=run_id,
    )


async def _wanted_outputs(session: AsyncSession, user_id: UUID) -> dict[str, bool]:
    """Which of this agent's three outputs the user has asked for."""
    config = await features.load(session, user_id)
    return {name: config.is_on(fid) for name, fid in OUTPUT_FEATURES.items()}


async def _allowed_routes(session: AsyncSession, user_id: UUID, routed: list[str]) -> list[str]:
    """Drop specialists whose feature is off, and say so once."""
    config = await features.load(session, user_id)
    kept = [
        name for name in routed if name in ROUTE_FEATURES and config.is_on(ROUTE_FEATURES[name])
    ]
    dropped = sorted(set(routed) - set(kept))
    if dropped:
        log.info("triage.routes_dropped", dropped=dropped)
    return kept


async def _store(
    session: AsyncSession,
    *,
    user_id: UUID,
    thread: EmailThread,
    outcome: TriageOutcome,
    wanted: dict[str, bool] | None = None,
) -> None:
    allow = wanted or dict.fromkeys(OUTPUT_FEATURES, True)
    routed = outcome.route_to

    # Each output written only if its own toggle is on. Null, not a
    # stale value: the inbox then shows "Not analysed" for that column,
    # which is what the user asked for, rather than a judgement they
    # turned off still sitting on the row.
    category = outcome.category if allow["category"] else None
    priority = outcome.priority if allow["priority"] else None
    reason = outcome.priority_reason if allow["priority"] else None
    technical = outcome.is_technical if allow["technical"] else None

    await session.execute(
        _UPSERT,
        {
            "thread_id": str(thread.id),
            "user_id": str(user_id),
            "category": category,
            "category_source": (
                None
                if category is None
                else ("user_rule" if outcome.source == "user_rule" else "agent")
            ),
            "priority": priority,
            "priority_reason": reason,
            "needs_reply": outcome.needs_reply,
            "is_technical": technical,
            "routed": routed,
            # Routed capabilities are queued; the rest do not apply. A
            # status per capability, never one global boolean (gap C4).
            "status_summary": "pending" if "summarizer" in routed else "not_applicable",
            "status_deadline": "pending" if "deadline" in routed else "not_applicable",
            "status_actions": "pending" if "action_items" in routed else "not_applicable",
            "content_version": thread.content_version,
            "pipeline_version": PIPELINE_VERSION,
        },
    )
    # Why a thread became important, preserved rather than overwritten.
    await session.execute(
        _SNAPSHOT,
        {
            "thread_id": str(thread.id),
            "user_id": str(user_id),
            "snapshot": json.dumps(
                {
                    "category": category,
                    "priority": priority,
                    "priority_reason": reason,
                    "needs_reply": outcome.needs_reply,
                    "is_technical": technical,
                    "route_to": outcome.route_to,
                    "source": outcome.source,
                    # What the agent concluded but was not allowed to
                    # store, so "why is this blank" has an answer later.
                    "withheld": sorted(name for name, on in allow.items() if not on),
                    "at": get_clock().now().isoformat(),
                }
            ),
            "content_version": thread.content_version,
            "pipeline_version": PIPELINE_VERSION,
            "run_id": str(outcome.run_id) if outcome.run_id else None,
        },
    )


async def _mark_skipped(
    session: AsyncSession, *, user_id: UUID, thread: EmailThread, reason: str
) -> None:
    status = "skipped_budget" if "budget" in reason else "skipped_disabled"
    await session.execute(
        _UPSERT,
        {
            "thread_id": str(thread.id),
            "user_id": str(user_id),
            "category": None,
            "category_source": None,
            "priority": None,
            "priority_reason": None,
            "needs_reply": None,
            "is_technical": None,
            "routed": [],
            "status_summary": status,
            "status_deadline": status,
            "status_actions": status,
            "content_version": thread.content_version,
            "pipeline_version": PIPELINE_VERSION,
        },
    )


async def _mark_failed(
    session: AsyncSession, *, user_id: UUID, thread: EmailThread, run_id: UUID
) -> None:
    await session.execute(
        _UPSERT,
        {
            "thread_id": str(thread.id),
            "user_id": str(user_id),
            "category": None,
            "category_source": None,
            "priority": None,
            "priority_reason": None,
            "needs_reply": None,
            "is_technical": None,
            "routed": [],
            "status_summary": "failed",
            "status_deadline": "failed",
            "status_actions": "failed",
            "content_version": thread.content_version,
            "pipeline_version": PIPELINE_VERSION,
        },
    )
    log.warning("triage.failed", thread_id=str(thread.id), run_id=str(run_id))
