"""Action items, with stated and inferred kept apart by the runtime.

The agent labels each item, and this module checks the label it cannot be
trusted to apply correctly:

**A `stated` item must resolve to words.** The claim is "the sender asked
for this", and the proof is the span. If the span does not resolve, the
item is **dropped**, not relabelled.

That is deliberately harsher than the entity handling in the summarizer,
and the difference is worth naming. A mislabelled entity is a noun that
may still be real -- calling it an interpretation rather than a quotation
loses nothing. A ``stated`` action item that cannot be quoted is a
fabricated request: it says a person asked this user to do something. Kept
as ``inferred``, it would sit on the user's task list as an obligation
nobody ever asked of them. So it goes.

The database agrees: ``action_stated_has_evidence`` rejects an agent-made
stated row with no span, so this is enforced twice and the second one
cannot be bypassed by a future caller.
"""

from __future__ import annotations

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

AGENT_ID = "action_items"
FEATURE_ID = "action_extraction"
PIPELINE_VERSION = "actions-1"

VALID_OWNERS = frozenset({"user", "sender", "other", "unclear"})
MAX_ITEMS = 10


@dataclass
class ExtractedAction:
    description: str
    owner: str
    source: str
    message_id: UUID | None = None
    evidence_char_start: int | None = None
    evidence_char_end: int | None = None
    quote: str | None = None


@dataclass
class ActionOutcome:
    thread_id: UUID
    items: list[ExtractedAction] = field(default_factory=list)
    follow_up_needed: bool = False
    #: How many the agent proposed as stated and could not support. A
    #: number worth watching: a model that keeps inventing quotations is a
    #: prompt problem, and it is invisible unless counted.
    dropped_unsupported: int = 0
    source: str = "agent"
    run_id: UUID | None = None
    cost_micros: int = 0


_CLEAR = text(
    """
    UPDATE action_items SET status = 'dismissed'
     WHERE thread_id = :thread_id
       AND created_by = 'agent'
       AND status = 'open'
       AND content_version < :content_version
    """
)

_INSERT = text(
    """
    INSERT INTO action_items
        (user_id, thread_id, message_id, description, owner, source,
         evidence_char_start, evidence_char_end, created_by, agent_run_id,
         content_version)
    VALUES (:user_id, :thread_id, :message_id, :description, :owner, :source,
            :char_start, :char_end, 'agent', :run_id, :content_version)
    RETURNING id
    """
)

_SET_STATUS = text(
    """
    UPDATE thread_intelligence
       SET status_actions = CAST(:status AS capability_status), updated_at = now()
     WHERE thread_id = :thread_id
    """
)


async def extract_actions(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    thread_id: UUID,
    user_initiated: bool = False,
) -> ActionOutcome | None:
    thread = await session.get(EmailThread, thread_id)
    if thread is None or thread.merged_into_thread_id is not None:
        return None

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
        feature_enabled=await features.is_enabled(session, user_id, FEATURE_ID),
    )
    if decision.decision is Decision.skip:
        status = "skipped_budget" if "budget" in decision.reason else "skipped_disabled"
        await session.execute(_SET_STATUS, {"thread_id": str(thread_id), "status": status})
        return None

    context = await build_thread_context(
        session,
        thread_id=thread_id,
        system=spec.system_prompt,
        question=(
            f"user_id: {user_id}\nthread_id: {thread_id}\nWhat needs to happen next in this thread?"
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
        return None

    resolver = await load_resolver(session, thread_id)
    outcome = _from_output(thread_id, result.output, resolver=resolver)
    outcome.run_id = result.run_id
    outcome.cost_micros = result.cost_micros
    await _store(session, user_id=user_id, thread=thread, outcome=outcome)
    return outcome


# ---------------------------------------------------------------------------
def _from_output(
    thread_id: UUID, output: dict[str, Any], *, resolver: SpanResolver
) -> ActionOutcome:
    items: list[ExtractedAction] = []
    dropped = 0

    for raw in output.get("items") or []:
        if not isinstance(raw, dict) or len(items) >= MAX_ITEMS:
            continue

        description = str(raw.get("description") or "").strip()
        if not description:
            continue

        source = "stated" if str(raw.get("source")) == "stated" else "inferred"
        owner = str(raw.get("owner") or "unclear")
        if owner not in VALID_OWNERS:
            owner = "unclear"

        span = resolver.resolve(raw)

        if source == "stated" and span is None:
            # A quotation that cannot be quoted. Dropped rather than
            # softened to 'inferred', because what it asserts is that
            # someone made this request.
            dropped += 1
            log.info("actions.unsupported_stated_item", description=description[:60])
            continue

        items.append(
            ExtractedAction(
                description=description[:300],
                owner=owner,
                source=source,
                message_id=span.message_id if span else None,
                evidence_char_start=span.char_start if span else None,
                evidence_char_end=span.char_end if span else None,
                quote=span.quote if span else None,
            )
        )

    return ActionOutcome(
        thread_id=thread_id,
        items=items,
        # Only meaningful if something survived. A thread whose only items
        # were dropped is not a thread the user is holding up.
        follow_up_needed=bool(output.get("follow_up_needed")) and bool(items),
        dropped_unsupported=dropped,
    )


async def _store(
    session: AsyncSession, *, user_id: UUID, thread: EmailThread, outcome: ActionOutcome
) -> None:
    await session.execute(
        _CLEAR, {"thread_id": str(thread.id), "content_version": thread.content_version}
    )

    for item in outcome.items:
        await session.execute(
            _INSERT,
            {
                "user_id": str(user_id),
                "thread_id": str(thread.id),
                "message_id": str(item.message_id) if item.message_id else None,
                "description": item.description,
                "owner": item.owner,
                "source": item.source,
                "char_start": item.evidence_char_start,
                "char_end": item.evidence_char_end,
                "run_id": str(outcome.run_id) if outcome.run_id else None,
                "content_version": thread.content_version,
            },
        )

    await session.execute(_SET_STATUS, {"thread_id": str(thread.id), "status": "ready"})
