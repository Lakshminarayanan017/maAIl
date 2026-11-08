"""The intelligence panel's data: six sections, every claim with its source.

Two routes, and the split is the point.

``GET`` reads. It never invokes a model, never queues anything, and costs
one set of indexed reads plus one ranked query for related context. That
is phase 8's third gate -- *no model call to re-open a thread whose
summary is current* -- made structural: the read path cannot call a model
because it does not import one.

``POST`` is the demand in demand-driven. Opening a thread does not spend
money; asking for analysis does, and the interface asks only for what the
``GET`` reported as missing. A ``GET`` that silently ran three agents
would make every scroll through the inbox a bill.

Every value carries ``provenance``, which is the spec's requirement
rendered as data rather than as a convention:

> The user should always be able to distinguish: Information explicitly
> present in the email. AI-generated interpretations. Information
> retrieved from external integrations.

``stated`` means the email says it and here is the span. ``interpreted``
means a model concluded it. ``retrieved`` means it came from somewhere
else entirely. The panel paints the three differently and cannot do that
from a value alone.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.database.models.thread import EmailThread
from app.modules.agents.defs import actions as action_service
from app.modules.agents.defs import deadline as deadline_service
from app.modules.agents.defs import summarizer as summary_service
from app.modules.harness.evidence import load_resolver
from app.modules.mcp import bootstrap
from app.modules.providers.llm.factory import provider_for
from app.modules.retrieval.related import find_related

router = APIRouter(tags=["intelligence"])
log = get_logger(__name__)

Provenance = Literal["stated", "interpreted", "retrieved"]


class EvidenceOut(BaseModel):
    """A span that has already been checked against the message text.

    ``quote`` is present because it resolved. The interface never needs to
    decide whether two integers are trustworthy; if the span were bad it
    would not be in this list.
    """

    message_id: UUID
    char_start: int
    char_end: int
    quote: str | None = None


class SummarySection(BaseModel):
    status: str
    summary: str | None = None
    bullet_points: list[str] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    #: Always "interpreted". A summary is by definition not in the email.
    provenance: Provenance = "interpreted"
    model: str | None = None
    #: True when the stored summary predates the newest message.
    stale: bool = False


class IntentSection(BaseModel):
    status: str
    intent: str | None = None
    reason: str | None = None
    confidence: str | None = None
    evidence: list[EvidenceOut] = Field(default_factory=list)
    provenance: Provenance = "interpreted"


class EntityOut(BaseModel):
    kind: str
    value: str
    provenance: Provenance
    evidence: EvidenceOut | None = None


class ActionItemOut(BaseModel):
    id: UUID
    description: str
    owner: str
    #: 'stated' | 'inferred'. Rendered differently, never merged.
    source: str
    status: str
    evidence: EvidenceOut | None = None
    #: Set when this item has already been turned into a task.
    task_id: UUID | None = None


class DeadlineOut(BaseModel):
    id: UUID
    #: What the sender wrote. Always shown, whatever happened to it.
    raw_phrase: str
    normalized_date: date | None
    date_type: str
    resolution_status: str
    confidence_band: str
    is_for_user: bool
    evidence: EvidenceOut | None = None

    @property
    def asks_a_question(self) -> bool:
        return self.resolution_status == "ambiguous"


class RelatedOut(BaseModel):
    thread_id: UUID
    subject: str | None
    sender: str | None
    latest_message_at: datetime | None
    category: str | None
    #: Why this is here. "Also from X" and "mentions Y" are different
    #: claims, and an unexplained list of threads is noise.
    because: str
    #: Retrieved, not interpreted: these are real threads, found by query.
    provenance: Provenance = "retrieved"


class ThreadIntelligenceOut(BaseModel):
    thread_id: UUID
    content_version: int

    # 1. Summary · 2. Intent · 3. Entities · 4. Actions · 5. Related ·
    # 6. Suggested response. The order is the spec's and the panel renders
    # them in it.
    summary: SummarySection
    intent: IntentSection
    entities: list[EntityOut] = Field(default_factory=list)
    action_items: list[ActionItemOut] = Field(default_factory=list)
    deadlines: list[DeadlineOut] = Field(default_factory=list)
    related: list[RelatedOut] = Field(default_factory=list)

    #: The slot. Phase 12 fills it, and saying so is better than an empty
    #: section the reader reads as a failure.
    suggested_response: dict[str, Any] = Field(
        default_factory=lambda: {"available": False, "arrives_in_phase": 12}
    )

    #: Per capability, never one global boolean.
    status_summary: str = "pending"
    status_deadline: str = "pending"
    status_actions: str = "pending"
    #: What a POST would actually run, so the interface offers the right
    #: button instead of guessing.
    missing: list[str] = Field(default_factory=list)


class AnalyseRequest(BaseModel):
    #: Which capabilities to run. Empty means "whatever is missing".
    capabilities: list[Literal["summary", "deadlines", "actions"]] = Field(default_factory=list)
    force: bool = False


_STATUS = text(
    """
    SELECT status_summary::text, status_deadline::text, status_actions::text,
           computed_from_content_version
      FROM thread_intelligence
     WHERE thread_id = :thread_id
    """
)

_ACTIONS = text(
    """
    SELECT a.id, a.description, a.owner, a.source, a.status,
           a.message_id, a.evidence_char_start, a.evidence_char_end,
           (SELECT t.id FROM tasks t WHERE t.action_item_id = a.id LIMIT 1)
      FROM action_items a
     WHERE a.thread_id = :thread_id AND a.status <> 'dismissed'
     ORDER BY (a.source = 'stated') DESC, a.created_at
    """
)

_DEADLINES = text(
    """
    SELECT id, raw_phrase, normalized_date, date_type::text,
           resolution_status::text, confidence_band, is_for_user,
           message_id, evidence_char_start, evidence_char_end
      FROM deadlines
     WHERE thread_id = :thread_id AND superseded_by IS NULL
     ORDER BY normalized_date NULLS LAST, created_at
    """
)

_NEWEST_SENDER = text(
    """
    SELECT from_email FROM email_messages
     WHERE thread_id = :thread_id AND NOT is_from_user AND deleted_at IS NULL
     ORDER BY sent_at DESC LIMIT 1
    """
)


async def _thread_or_404(auth: AuthContext, thread_id: UUID) -> EmailThread:
    thread = await auth.session.get(EmailThread, thread_id)
    if thread is None or thread.merged_into_thread_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such thread")
    return thread


@router.get(
    "/threads/{thread_id}/intelligence",
    response_model=ThreadIntelligenceOut,
    summary="Everything known about one thread, with evidence",
)
async def read_intelligence(thread_id: UUID, auth: AuthContext) -> ThreadIntelligenceOut:
    """Reads only. No model, no queue, no cost."""
    thread = await _thread_or_404(auth, thread_id)
    session = auth.session

    status_row = (await session.execute(_STATUS, {"thread_id": str(thread_id)})).first()
    status_summary = str(status_row[0]) if status_row else "pending"
    status_deadline = str(status_row[1]) if status_row else "pending"
    status_actions = str(status_row[2]) if status_row else "pending"

    resolver = await load_resolver(session, thread_id)

    def span(
        message_id: Any, start: Any, end: Any, *, fallback_quote: str | None = None
    ) -> EvidenceOut | None:
        resolved = resolver.resolve(
            {"message_id": message_id, "char_start": start, "char_end": end}
        )
        if resolved is None:
            return None
        return EvidenceOut(
            message_id=resolved.message_id,
            char_start=resolved.char_start,
            char_end=resolved.char_end,
            quote=resolved.quote or fallback_quote,
        )

    # ---------------------------------------------------------- summary
    stored = await summary_service.read_stored(
        session, thread_id=thread_id, content_version=thread.content_version
    )
    if stored is None:
        # Nothing for this content version. An older summary may exist,
        # and showing it marked stale is more useful than showing nothing
        # -- but it is never presented as current.
        stored = await summary_service.read_stored(
            session, thread_id=thread_id, content_version=thread.content_version - 1
        )
        is_stale = stored is not None
    else:
        is_stale = False

    if stored is None:
        summary_section = SummarySection(status=status_summary)
        intent_section = IntentSection(status=status_summary)
        entities: list[EntityOut] = []
    else:
        evidence = [
            found
            for found in (
                span(item.get("message_id"), item.get("char_start"), item.get("char_end"))
                for item in stored.evidence
            )
            if found is not None
        ]
        # The gate, at the point it has to hold: no resolvable evidence
        # means the summary is not offered as a value. The interface shows
        # "not determined", which is what AiValue does with an empty list.
        summary_section = SummarySection(
            status="ready" if stored.summary and evidence else status_summary,
            summary=stored.summary or None,
            bullet_points=stored.bullet_points,
            evidence=evidence,
            stale=is_stale,
        )
        intent_evidence = [
            found
            for found in (
                span(item.get("message_id"), item.get("char_start"), item.get("char_end"))
                for item in stored.intent_evidence
            )
            if found is not None
        ]
        intent_section = IntentSection(
            status="ready" if stored.intent and intent_evidence else status_summary,
            intent=stored.intent,
            reason=stored.intent_reason,
            confidence=stored.intent_confidence,
            evidence=intent_evidence,
        )
        entities = [
            EntityOut(
                kind=str(raw.get("kind")),
                value=str(raw.get("value")),
                provenance=("stated" if raw.get("provenance") == "stated" else "interpreted"),
                evidence=span(
                    raw.get("message_id"),
                    raw.get("char_start"),
                    raw.get("char_end"),
                    fallback_quote=str(raw.get("quote")) if raw.get("quote") else None,
                ),
            )
            for raw in stored.entities
            if raw.get("kind") and raw.get("value")
        ]

    # ---------------------------------------------------------- actions
    action_items = [
        ActionItemOut(
            id=row[0],
            description=str(row[1]),
            owner=str(row[2]),
            source=str(row[3]),
            status=str(row[4]),
            evidence=span(row[5], row[6], row[7]),
            task_id=row[8],
        )
        for row in (await session.execute(_ACTIONS, {"thread_id": str(thread_id)})).all()
    ]

    deadlines = [
        DeadlineOut(
            id=row[0],
            raw_phrase=str(row[1]),
            normalized_date=row[2],
            date_type=str(row[3]),
            resolution_status=str(row[4]),
            confidence_band=str(row[5]),
            is_for_user=bool(row[6]),
            evidence=span(row[7], row[8], row[9], fallback_quote=str(row[1])),
        )
        for row in (await session.execute(_DEADLINES, {"thread_id": str(thread_id)})).all()
    ]

    # ---------------------------------------------------------- related
    sender = await session.scalar(_NEWEST_SENDER, {"thread_id": str(thread_id)})
    related = [
        RelatedOut(
            thread_id=item.thread_id,
            subject=item.subject,
            sender=item.sender,
            latest_message_at=item.latest_message_at,
            category=item.category,
            because=item.because,
        )
        for item in await find_related(
            session, thread_id=thread_id, sender=str(sender) if sender else None
        )
    ]

    missing: list[str] = []
    if summary_section.status != "ready" or is_stale:
        missing.append("summary")
    if status_deadline not in ("ready", "running"):
        missing.append("deadlines")
    if status_actions not in ("ready", "running"):
        missing.append("actions")

    return ThreadIntelligenceOut(
        thread_id=thread_id,
        content_version=thread.content_version,
        summary=summary_section,
        intent=intent_section,
        entities=entities,
        action_items=action_items,
        deadlines=deadlines,
        related=related,
        status_summary=status_summary,
        status_deadline=status_deadline,
        status_actions=status_actions,
        missing=missing,
    )


@router.post(
    "/threads/{thread_id}/intelligence",
    response_model=ThreadIntelligenceOut,
    dependencies=[Depends(require_csrf)],
    summary="Analyse one thread on demand",
)
async def analyse_thread(
    thread_id: UUID,
    body: AnalyseRequest,
    auth: AuthContext,
) -> ThreadIntelligenceOut:
    """Run the missing capabilities, then return the whole panel.

    Synchronous. The reader is looking at the panel and waiting, and
    queueing would mean a spinner plus a stream for a job that takes
    seconds. The queue is for work nobody is watching.

    One failing capability does not take the others down: a thread whose
    deadline pass failed while its summary succeeded has to be able to say
    exactly that, which is the whole reason the statuses are per
    capability (gap C4).
    """
    await _thread_or_404(auth, thread_id)
    runtime = bootstrap.runtime()

    wanted = set(body.capabilities) or {"summary", "deadlines", "actions"}
    timezone_name = await _user_timezone(auth)

    plan: list[tuple[str, str]] = [
        ("summary", summary_service.AGENT_ID),
        ("deadlines", deadline_service.AGENT_ID),
        ("actions", action_service.AGENT_ID),
    ]

    for capability, agent_id in plan:
        if capability not in wanted:
            continue
        spec = runtime.agents.get(agent_id)
        if spec is None:
            log.warning("intelligence.agent_missing", agent=agent_id)
            continue

        provider = provider_for(spec.tier)
        try:
            if capability == "summary":
                await summary_service.summarize_thread(
                    auth.session,
                    spec=spec,
                    provider=provider,
                    host=runtime.host,
                    user_id=auth.user_id,
                    thread_id=thread_id,
                    user_initiated=True,
                    force=body.force,
                )
            elif capability == "deadlines":
                await deadline_service.extract_deadlines(
                    auth.session,
                    spec=spec,
                    provider=provider,
                    host=runtime.host,
                    user_id=auth.user_id,
                    thread_id=thread_id,
                    timezone_name=timezone_name,
                    user_initiated=True,
                )
            else:
                await action_service.extract_actions(
                    auth.session,
                    spec=spec,
                    provider=provider,
                    host=runtime.host,
                    user_id=auth.user_id,
                    thread_id=thread_id,
                    user_initiated=True,
                )
        except Exception:
            # Logged and carried past. The status column already says
            # 'failed' for whichever capability this was, so the panel
            # reports it honestly instead of the request 500ing and the
            # reader losing the sections that did work.
            log.exception("intelligence.capability_failed", capability=capability)

    return await read_intelligence(thread_id, auth)


async def _user_timezone(auth: AuthContext) -> str:
    stored = await auth.session.scalar(
        text("SELECT coalesce(timezone, 'UTC') FROM users WHERE id = :id"),
        {"id": str(auth.user_id)},
    )
    return str(stored or "UTC")


AuthDep = Annotated[AuthContext, Depends()]
