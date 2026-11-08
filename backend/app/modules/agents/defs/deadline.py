"""Deadlines: deterministic extraction first, then classification only.

The order here is the cost architecture in miniature.

**Code finds the phrases.** ``ingest/date_parser`` walks the stripped text
and returns every date-ish phrase with its span and, where the phrase
names a resolvable day, the resolved date. No model.

**A thread with no candidates never reaches a model.** That is the common
case and it costs one regex pass. Invariant 3: a cheap thing decides what
the expensive thing looks at.

**The model classifies, and cannot write a date.** Its schema has no date
field. Resolved dates are taken from the candidate by index, so a wrong
answer here can be a wrong *label* and never a wrong date -- which is the
difference between "Maail thinks this is not urgent" and "Maail told me
the wrong day".

The storage rules follow from the schema's own constraint: a row that
claims to be resolved carries a date, and a row with no date may not
claim to be resolved. ``ambiguous`` therefore stores **no date at all**,
and the interface renders it as a question with the sender's phrase
quoted. Nothing is invented to fill the column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.thread import EmailMessage, EmailThread
from app.modules.agents.runtime import RunOutcome, run_agent
from app.modules.agents.runtime.spec import AgentSpec
from app.modules.features import service as features
from app.modules.harness import budget as budget_manager
from app.modules.harness.context_builder import build_thread_context
from app.modules.harness.planner import Decision, IntelligenceRequest, Tier, plan
from app.modules.ingest.date_parser import DateCandidate, find_date_candidates
from app.modules.mcp.client_manager import ClientHost
from app.modules.providers.llm.base import LLMProvider

log = get_logger(__name__)

AGENT_ID = "deadline"
FEATURE_ID = "deadline_detection"
PIPELINE_VERSION = "deadline-1"

VALID_TYPES = frozenset(
    {"explicit_absolute", "explicit_relative", "soft_request", "vague", "recurring"}
)
#: What an agent may say. ``user_confirmed`` and ``user_corrected`` exist
#: in the schema but are not an agent's to write -- only a person can
#: confirm their own deadline.
AGENT_RESOLUTIONS = frozenset({"resolved", "ambiguous", "unresolved"})


@dataclass
class ExtractedDeadline:
    message_id: UUID
    raw_phrase: str
    date_type: str
    resolution_status: str
    confidence_band: str
    normalized_date: Any = None
    is_for_user: bool = True
    reason: str | None = None
    evidence_char_start: int | None = None
    evidence_char_end: int | None = None


@dataclass
class DeadlineOutcome:
    thread_id: UUID
    deadlines: list[ExtractedDeadline] = field(default_factory=list)
    #: How the answer was reached: 'no_candidates' means code settled it
    #: and no model ran. Recorded so the share is measurable.
    source: str = "agent"
    candidates_found: int = 0
    run_id: UUID | None = None
    cost_micros: int = 0


_CLEAR = text(
    """
    UPDATE deadlines SET superseded_by = id
     WHERE thread_id = :thread_id
       AND created_by = 'agent'
       AND superseded_by IS NULL
       AND content_version < :content_version
    """
)

_INSERT = text(
    """
    INSERT INTO deadlines
        (user_id, thread_id, message_id, raw_phrase, normalized_date, timezone,
         date_type, resolution_status, confidence_band,
         evidence_char_start, evidence_char_end, is_for_user, created_by,
         content_version, agent_run_id)
    VALUES (:user_id, :thread_id, :message_id, :raw_phrase, :normalized_date, :timezone,
            CAST(:date_type AS date_type), CAST(:resolution_status AS date_resolution),
            :confidence_band, :char_start, :char_end, :is_for_user, 'agent',
            :content_version, :run_id)
    """
)

_SET_STATUS = text(
    """
    UPDATE thread_intelligence
       SET status_deadline = CAST(:status AS capability_status), updated_at = now()
     WHERE thread_id = :thread_id
    """
)


def render_candidates(candidates: list[tuple[UUID, DateCandidate]]) -> str:
    """The numbered list the agent answers about.

    The format is parsed by the extractive provider as well, so the two
    are coupled and a test keeps them in step. Each line carries the
    parser's own resolution, which is what the agent must not contradict
    and cannot overwrite.
    """
    lines = ["Date candidates found in this thread:"]
    for index, (_, candidate) in enumerate(candidates):
        resolved = candidate.resolved.isoformat() if candidate.resolved else "none"
        lines.append(
            f'  [{index}] "{candidate.text}" kind={candidate.kind.value} '
            f"resolved={resolved} confidence={candidate.confidence_band} "
            f"rule={candidate.rule}"
        )
    return "\n".join(lines)


async def collect_candidates(
    session: AsyncSession, *, thread_id: UUID, timezone_name: str = "UTC"
) -> list[tuple[UUID, DateCandidate]]:
    """Every date phrase in the thread, with the message it came from.

    Deterministic, free, and run before anything else. A thread that
    returns an empty list here is finished: there is no date to classify,
    so there is nothing for a model to be wrong about.
    """
    messages = (
        await session.scalars(
            select(EmailMessage)
            .where(EmailMessage.thread_id == thread_id, EmailMessage.deleted_at.is_(None))
            .order_by(EmailMessage.sent_at)
        )
    ).all()

    found: list[tuple[UUID, DateCandidate]] = []
    for message in messages:
        body = message.body_text_stripped or message.snippet or ""
        if not body:
            continue
        for candidate in find_date_candidates(
            body, sent_at=message.sent_at, user_timezone=timezone_name
        ):
            found.append((message.id, candidate))
    return found


async def extract_deadlines(
    session: AsyncSession,
    *,
    spec: AgentSpec,
    provider: LLMProvider,
    host: ClientHost,
    user_id: UUID,
    thread_id: UUID,
    timezone_name: str = "UTC",
    user_initiated: bool = False,
) -> DeadlineOutcome | None:
    thread = await session.get(EmailThread, thread_id)
    if thread is None or thread.merged_into_thread_id is not None:
        return None

    # Before the regex pass, not after: a disabled feature does no work
    # at all, and the capability says why rather than going quiet.
    enabled = await features.is_enabled(session, user_id, FEATURE_ID)
    if not enabled:
        await session.execute(
            _SET_STATUS, {"thread_id": str(thread_id), "status": "skipped_disabled"}
        )
        return None

    candidates = await collect_candidates(session, thread_id=thread_id, timezone_name=timezone_name)

    if not candidates:
        # Settled by code. The capability is 'ready' with nothing in it,
        # which is a different statement from 'pending' and from 'failed',
        # and the panel says so.
        await session.execute(_SET_STATUS, {"thread_id": str(thread_id), "status": "ready"})
        log.info("deadline.no_candidates", thread_id=str(thread_id))
        return DeadlineOutcome(thread_id=thread_id, source="no_candidates")

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
    # Asked again at the planner, from the same value. The planner is
    # the one place every path through the system converges, and a
    # caller that forgot would be invisible there if it were implicit.
    decision = await plan(session, request, feature_enabled=enabled)
    if decision.decision is Decision.skip:
        status = "skipped_budget" if "budget" in decision.reason else "skipped_disabled"
        await session.execute(_SET_STATUS, {"thread_id": str(thread_id), "status": status})
        return None

    context = await build_thread_context(
        session,
        thread_id=thread_id,
        system=spec.system_prompt,
        question=(
            f"user_id: {user_id}\nthread_id: {thread_id}\n"
            f"{render_candidates(candidates)}\n\n"
            "Classify each candidate by index."
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

    extracted = _from_output(result.output, candidates=candidates, timezone_name=timezone_name)
    outcome = DeadlineOutcome(
        thread_id=thread_id,
        deadlines=extracted,
        source="agent",
        candidates_found=len(candidates),
        run_id=result.run_id,
        cost_micros=result.cost_micros,
    )
    await _store(session, user_id=user_id, thread=thread, outcome=outcome)
    return outcome


# ---------------------------------------------------------------------------
def _from_output(
    output: dict[str, Any],
    *,
    candidates: list[tuple[UUID, DateCandidate]],
    timezone_name: str,
) -> list[ExtractedDeadline]:
    """Map classifications onto candidates. The candidate wins on facts.

    Everything factual -- the phrase, the span, the date -- comes from the
    candidate. The agent contributes judgement only, and a judgement that
    contradicts the parser is corrected rather than stored.
    """
    out: list[ExtractedDeadline] = []
    seen: set[int] = set()

    for raw in output.get("deadlines") or []:
        if not isinstance(raw, dict):
            continue
        try:
            index = int(raw.get("candidate_index", -1))
        except (TypeError, ValueError):
            continue
        # An index the agent invented refers to no phrase, so there is
        # nothing to store and nothing to quote.
        if index < 0 or index >= len(candidates) or index in seen:
            continue
        seen.add(index)

        if not bool(raw.get("is_deadline", False)):
            continue

        message_id, candidate = candidates[index]

        date_type = str(raw.get("date_type") or candidate.kind.value)
        if date_type not in VALID_TYPES:
            date_type = candidate.kind.value

        status = str(raw.get("resolution_status") or "")
        if status not in AGENT_RESOLUTIONS:
            status = "resolved" if candidate.resolved else "unresolved"

        # Two corrections, both of which stop a confident wrong date.
        #
        # The agent says resolved and the parser found no day: there is no
        # date to store, so the claim cannot stand as resolved.
        if status == "resolved" and candidate.resolved is None:
            status = "unresolved"
            log.info("deadline.resolved_without_a_date", phrase=candidate.text[:40])
        # The agent says ambiguous: the date is withheld on purpose. A
        # question that also shows a date is not a question.
        normalized = candidate.resolved if status == "resolved" else None

        band = str(raw.get("confidence_band") or candidate.confidence_band)
        if band not in ("high", "medium", "low"):
            band = candidate.confidence_band

        out.append(
            ExtractedDeadline(
                message_id=message_id,
                raw_phrase=candidate.text,
                date_type=date_type,
                resolution_status=status,
                confidence_band=band,
                normalized_date=normalized,
                is_for_user=bool(raw.get("is_for_user", True)),
                reason=str(raw.get("reason") or "")[:200] or None,
                evidence_char_start=candidate.start,
                evidence_char_end=candidate.end,
            )
        )

    return out


async def _store(
    session: AsyncSession, *, user_id: UUID, thread: EmailThread, outcome: DeadlineOutcome
) -> None:
    """Supersede the previous pass, then write this one.

    Superseded rather than deleted: a deadline the user has already seen
    and perhaps acted on should not silently vanish because a newer
    message changed the thread.
    """
    await session.execute(
        _CLEAR,
        {"thread_id": str(thread.id), "content_version": thread.content_version},
    )

    for deadline in outcome.deadlines:
        await session.execute(
            _INSERT,
            {
                "user_id": str(user_id),
                "thread_id": str(thread.id),
                "message_id": str(deadline.message_id),
                "raw_phrase": deadline.raw_phrase,
                "normalized_date": deadline.normalized_date,
                "timezone": None,
                "date_type": deadline.date_type,
                "resolution_status": deadline.resolution_status,
                "confidence_band": deadline.confidence_band,
                "char_start": deadline.evidence_char_start,
                "char_end": deadline.evidence_char_end,
                "is_for_user": deadline.is_for_user,
                "content_version": thread.content_version,
                "run_id": str(outcome.run_id) if outcome.run_id else None,
            },
        )

    await session.execute(_SET_STATUS, {"thread_id": str(thread.id), "status": "ready"})
