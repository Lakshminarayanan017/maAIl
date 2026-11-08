"""The Command Center's numbers. Aggregates over stored intelligence only.

> Zero model calls to open, filter, sort or paginate the inbox.
> (09-execution-plan.md, phase 7)

Nothing here reprocesses an email. Every figure is a count, or a read of a
judgement an agent already made and wrote down -- which is the whole
reason ``thread_intelligence`` is a table rather than something recomputed
on the way to the screen.

The response keeps **counts and classifications apart**, deliberately:

> counts and AI-generated classifications must be clearly separated. We
> shouldn't present estimated urgency as a factual status.
> (08-ui-spec.md, screen 03)

So ``counts`` holds facts -- how many emails, how many unread -- and
``attention`` holds judgements, each carrying the reason an agent gave.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import AuthContext
from app.core.clock import get_clock

router = APIRouter(prefix="/overview", tags=["overview"])


class Counts(BaseModel):
    """Facts. Nothing here was estimated by anything."""

    threads: int
    unread: int
    today: int
    #: How many threads have been through Triage at all, so the screen can
    #: say "5 of 24 analysed" rather than implying the rest were dull.
    analysed: int


class PriorityCard(BaseModel):
    """A judgement, and the evidence for it."""

    thread_id: UUID
    subject: str | None
    sender: str | None
    category: str | None
    priority: int
    #: Never an unexplained badge.
    priority_reason: str | None
    is_technical: bool
    latest_message_at: datetime | None


class Overview(BaseModel):
    greeting: str
    counts: Counts
    attention: list[PriorityCard] = Field(
        default_factory=list,
        description="AI-classified, each with its reason. Not a count.",
    )
    #: Empty until the Deadline agent lands in phase 9. Present so the
    #: screen's shape is honest about what is still coming.
    upcoming_deadlines: list[dict[str, str]] = Field(default_factory=list)
    technical_count: int = 0


_COUNTS = text(
    """
    SELECT
      count(*) FILTER (WHERE t.message_count > 0),
      count(*) FILTER (WHERE t.unread_count > 0),
      count(*) FILTER (WHERE t.latest_message_at >= date_trunc('day', now())),
      count(ti.thread_id)
    FROM email_threads t
    LEFT JOIN thread_intelligence ti ON ti.thread_id = t.id
   WHERE t.merged_into_thread_id IS NULL
    """
)

_ATTENTION = text(
    """
    SELECT t.id, t.subject, ti.category::text, ti.priority, ti.priority_reason,
           coalesce(ti.is_technical, false), t.latest_message_at,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.id AND NOT m.is_from_user AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1)
      FROM thread_intelligence ti
      JOIN email_threads t ON t.id = ti.thread_id
     WHERE ti.priority >= 2
       AND t.merged_into_thread_id IS NULL
     ORDER BY ti.priority DESC, t.latest_message_at DESC NULLS LAST
     LIMIT :limit
    """
)

_TECHNICAL = text("SELECT count(*) FROM thread_intelligence WHERE is_technical AND priority >= 1")


def _greeting(name: str | None) -> str:
    """Time-aware, as the spec asks."""
    hour = get_clock().now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {name}" if name else f"Good {part}"


@router.get("", response_model=Overview, summary="The Command Center")
async def read_overview(auth: AuthContext) -> Overview:
    name = await auth.session.scalar(
        text("SELECT coalesce(name, split_part(email::text, '@', 1)) FROM users WHERE id = :id"),
        {"id": str(auth.user_id)},
    )

    counts_row = (await auth.session.execute(_COUNTS)).one()
    attention_rows = (await auth.session.execute(_ATTENTION, {"limit": 6})).all()
    technical = await auth.session.scalar(_TECHNICAL)

    return Overview(
        greeting=_greeting(str(name) if name else None),
        counts=Counts(
            threads=int(counts_row[0] or 0),
            unread=int(counts_row[1] or 0),
            today=int(counts_row[2] or 0),
            analysed=int(counts_row[3] or 0),
        ),
        attention=[
            PriorityCard(
                thread_id=row[0],
                subject=row[1],
                sender=row[7],
                category=row[2],
                priority=int(row[3] or 0),
                priority_reason=row[4],
                is_technical=bool(row[5]),
                latest_message_at=row[6],
            )
            for row in attention_rows
        ],
        technical_count=int(technical or 0),
    )
