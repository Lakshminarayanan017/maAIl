"""Summary, intent and entities for one thread. On demand, cached by content.

Nothing queues this. A summary is produced when a person opens a thread
and the panel asks for one, which is invariant 3 in practice: the cheapest
possible intelligence is intelligence nobody needed.

The cache is the uniqueness of ``(thread_id, content_version)`` on both
tables it writes, so "has this already been done" is one indexed read and
not a policy anyone has to remember. Phase 8's third gate -- *no model
call to re-open a thread whose summary is current* -- is that read.

Every stored claim passes the span resolver first. A summary whose
evidence does not resolve is stored **with empty evidence**, which is what
makes the panel render "not determined" rather than a confident sentence
nobody can check. Storing it either way is deliberate: the run happened,
it cost money, and hiding that it produced an unusable answer would make
the failure invisible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.thread import EmailThread
from app.modules.agents.runtime import RunOutcome, run_agent
from app.modules.agents.runtime.spec import AgentSpec
from app.modules.features import service as features
from app.modules.harness import budget as budget_manager
from app.modules.harness.context_builder import build_thread_context
from app.modules.harness.evidence import SpanResolver, load_resolver
from app.modules.harness.planner import Decision, IntelligenceRequest, Tier, plan
from app.modules.mcp.client_manager import ClientHost
from app.modules.providers.llm.base import LLMProvider

log = get_logger(__name__)

AGENT_ID = "summarizer"
FEATURE_ID = "instant_summaries"
PIPELINE_VERSION = "summarizer-1"

VALID_INTENTS = frozenset(
    {
        "reply_requested",
        "action_requested",
        "information_only",
        "deadline_set",
        "approval_requested",
        "scheduling",
        "other",
    }
)
VALID_ENTITY_KINDS = frozenset(
    {"project", "repository", "technology", "date", "error_message", "person", "organization"}
)
MAX_ENTITIES = 20


@dataclass
class SummaryOutcome:
    thread_id: UUID
    summary: str
    bullet_points: list[str]
    evidence: list[dict[str, Any]]
    intent: str | None
    intent_reason: str | None
    intent_confidence: str | None
    intent_evidence: list[dict[str, Any]]
    entities: list[dict[str, Any]] = field(default_factory=list)
    content_version: int = 0
    source: str = "agent"
    run_id: UUID | None = None
    cost_micros: int = 0

    @property
    def grounded(self) -> bool:
        """Did anything survive the resolver? The panel's whole question."""
        return bool(self.evidence)


_READ_SUMMARY = text(
    """
    SELECT s.summary, s.bullet_points, s.evidence, s.content_version,
           i.intent, i.intent_reason, i.intent_confidence, i.intent_evidence, i.entities
      FROM thread_summaries s
      FULL OUTER JOIN thread_insights i
        ON i.thread_id = s.thread_id AND i.content_version = s.content_version
     WHERE coalesce(s.thread_id, i.thread_id) = :thread_id
       AND coalesce(s.content_version, i.content_version) = :content_version
       AND (s.kind = 'short' OR s.kind IS NULL)
     LIMIT 1
    """
)

_WRITE_SUMMARY = text(
    """
    INSERT INTO thread_summaries
        (thread_id, user_id, kind, summary, bullet_points, evidence,
         content_version, model, agent_run_id)
    VALUES (:thread_id, :user_id, 'short', :summary, CAST(:bullets AS jsonb),
            CAST(:evidence AS jsonb), :content_version, :model, :run_id)
    ON CONFLICT (thread_id, kind, content_version) DO UPDATE SET
        summary = excluded.summary,
        bullet_points = excluded.bullet_points,
        evidence = excluded.evidence,
        model = excluded.model,
        agent_run_id = excluded.agent_run_id
    """
)

_WRITE_INSIGHT = text(
    """
    INSERT INTO thread_insights
        (thread_id, user_id, intent, intent_reason, intent_confidence,
         intent_evidence, entities, content_version, model, agent_run_id)
    VALUES (:thread_id, :user_id, :intent, :intent_reason, :intent_confidence,
            CAST(:intent_evidence AS jsonb), CAST(:entities AS jsonb),
            :content_version, :model, :run_id)
    ON CONFLICT (thread_id, content_version) DO UPDATE SET
        intent = excluded.intent,
        intent_reason = excluded.intent_reason,
        intent_confidence = excluded.intent_confidence,
        intent_evidence = excluded.intent_evidence,
        entities = excluded.entities,
        model = excluded.model,
        agent_run_id = excluded.agent_run_id
    """
)

_SET_STATUS = text(
    """
    UPDATE thread_intelligence
       SET status_summary = CAST(:status AS capability_status), updated_at = now()
     WHERE thread_id = :thread_id
    """
)


async def read_stored(
    session: AsyncSession, *, thread_id: UUID, content_version: int
) -> SummaryOutcome | None:
    """The cache read. One indexed lookup, no model, no tools."""
    row = (
        await session.execute(
            _READ_SUMMARY, {"thread_id": str(thread_id), "content_version": content_version}
        )
    ).first()
    if row is None:
        return None

    return SummaryOutcome(
        thread_id=thread_id,
        summary=str(row[0] or ""),
        bullet_points=list(row[1] or []),
        evidence=list(row[2] or []),
        intent=row[4],
        intent_reason=row[5],
        intent_confidence=row[6],
        intent_evidence=list(row[7] or []),
        entities=list(row[8] or []),
        content_version=content_version,
        source="stored",
    )


async def summarize_thread(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    thread_id: UUID,
    user_initiated: bool = True,
    force: bool = False,
) -> SummaryOutcome | None:
    """Summarise one thread, or return what is already stored for it."""
    thread = await session.get(EmailThread, thread_id)
    if thread is None or thread.merged_into_thread_id is not None:
        return None

    if not force:
        stored = await read_stored(
            session, thread_id=thread_id, content_version=thread.content_version
        )
        if stored is not None:
            log.info("summarizer.stored", thread_id=str(thread_id))
            return stored

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
        # The toggle gates real execution, and it is checked before the
        # cache as well as before the model: a disabled feature serving
        # an old cached answer is still the feature running.
        feature_enabled=await features.is_enabled(session, user_id, FEATURE_ID),
    )
    if decision.decision is Decision.skip:
        await _set_status(session, thread_id, decision.reason)
        log.info("summarizer.skipped", thread_id=str(thread_id), reason=decision.reason)
        return None
    if decision.decision is Decision.cached and not force:
        # The result cache says this was done, but the stored read above
        # found nothing, so the cache row has outlived its result. Trust
        # the table, not the key: the user is waiting for a summary and
        # the cache cannot produce one.
        log.info("summarizer.cache_without_result", thread_id=str(thread_id))

    context = await build_thread_context(
        session,
        thread_id=thread_id,
        system=spec.system_prompt,
        question=(
            f"user_id: {user_id}\nthread_id: {thread_id}\n"
            "Summarise this thread, say what the sender expects, and list what it names."
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
        trigger="user_requested" if user_initiated else "thread_ingested",
        subject_type="thread",
        subject_id=thread_id,
    )
    await budget_manager.spend(session, user_id, result.cost_micros)

    if result.outcome is not RunOutcome.succeeded or result.output is None:
        await session.execute(_SET_STATUS, {"thread_id": str(thread_id), "status": "failed"})
        log.warning("summarizer.failed", thread_id=str(thread_id), run_id=str(result.run_id))
        return None

    resolver = await load_resolver(session, thread_id)
    outcome = _from_output(
        thread_id,
        result.output,
        resolver=resolver,
        content_version=thread.content_version,
        run_id=result.run_id,
    )
    outcome.cost_micros = result.cost_micros
    await _store(session, user_id=user_id, outcome=outcome, model=provider.model_id)
    return outcome


# ---------------------------------------------------------------------------
def _from_output(
    thread_id: UUID,
    output: dict[str, Any],
    *,
    resolver: SpanResolver,
    content_version: int,
    run_id: UUID,
) -> SummaryOutcome:
    """Everything the model said, filtered to what can be checked."""
    evidence = [span.as_dict() for span in resolver.resolve_all(output.get("evidence"))]

    intent = str(output.get("intent") or "")
    if intent not in VALID_INTENTS:
        intent = "other"

    entities: list[dict[str, Any]] = []
    for raw in output.get("entities") or []:
        if not isinstance(raw, dict) or len(entities) >= MAX_ENTITIES:
            continue
        kind = str(raw.get("kind") or "")
        value = str(raw.get("value") or "").strip()
        if kind not in VALID_ENTITY_KINDS or not value:
            continue

        span = resolver.resolve(raw)
        claimed = str(raw.get("provenance") or "interpreted")

        # The correction that matters. An entity claiming to be *stated* in
        # the email has to be able to point at it; one that cannot is an
        # interpretation that was labelled wrongly, and it is relabelled
        # rather than dropped -- it may still be right, it is just not a
        # quotation.
        if claimed == "stated" and span is None:
            provenance = "interpreted"
            log.info("summarizer.entity_relabelled", kind=kind, value=value[:40])
        else:
            provenance = "stated" if claimed == "stated" else "interpreted"

        entities.append(
            {
                "kind": kind,
                "value": value[:200],
                "provenance": provenance,
                **(
                    {
                        "message_id": str(span.message_id),
                        "char_start": span.char_start,
                        "char_end": span.char_end,
                        "quote": span.quote,
                    }
                    if span
                    else {}
                ),
            }
        )

    summary = str(output.get("summary") or "").strip()
    bullets = [str(point)[:200] for point in (output.get("bullet_points") or [])][:5]

    return SummaryOutcome(
        thread_id=thread_id,
        # A summary with no resolvable evidence is kept as text but the
        # panel will not render it as a value. Blanking it here would lose
        # the record of what the run actually produced.
        summary=summary[:600],
        bullet_points=bullets,
        evidence=evidence,
        intent=intent,
        intent_reason=str(output.get("intent_reason") or "")[:200] or None,
        intent_confidence=(
            str(output.get("intent_confidence"))
            if output.get("intent_confidence") in ("high", "medium", "low")
            else "low"
        ),
        # The intent's own evidence: the summary's spans, since the intent
        # was read from the same sentences. A separate span list would be
        # the model pointing twice at one place.
        intent_evidence=evidence,
        entities=entities,
        content_version=content_version,
        source="agent",
        run_id=run_id,
    )


async def _store(
    session: AsyncSession, *, user_id: UUID, outcome: SummaryOutcome, model: str
) -> None:
    common = {
        "thread_id": str(outcome.thread_id),
        "user_id": str(user_id),
        "content_version": outcome.content_version,
        "model": model,
        "run_id": str(outcome.run_id) if outcome.run_id else None,
    }
    await session.execute(
        _WRITE_SUMMARY,
        {
            **common,
            "summary": outcome.summary,
            "bullets": json.dumps(outcome.bullet_points),
            "evidence": json.dumps(outcome.evidence),
        },
    )
    await session.execute(
        _WRITE_INSIGHT,
        {
            **common,
            "intent": outcome.intent,
            "intent_reason": outcome.intent_reason,
            "intent_confidence": outcome.intent_confidence,
            "intent_evidence": json.dumps(outcome.intent_evidence),
            "entities": json.dumps(outcome.entities),
        },
    )
    await session.execute(_SET_STATUS, {"thread_id": str(outcome.thread_id), "status": "ready"})


async def _set_status(session: AsyncSession, thread_id: UUID, reason: str) -> None:
    status = "skipped_budget" if "budget" in reason else "skipped_disabled"
    await session.execute(_SET_STATUS, {"thread_id": str(thread_id), "status": status})
