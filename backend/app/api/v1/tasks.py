"""Tasks, deadlines, and the two places a person corrects the machine.

Screen 09's four tabs are four SQL filters. Zero model calls to list,
filter or complete anything -- the judgements were made when the thread
was analysed, and reading them back is a query.

Two routes here are the honest half of the feature:

``POST /action-items/{id}/confirm`` is what makes a suggestion a task. An
AI-extracted action item sits in its own list until a person accepts it;
it never appears among their commitments on its own. ``tasks.origin`` and
``tasks.confirmed_at`` are what that looks like in the schema.

``POST /deadlines/{id}/resolve`` is the ambiguity resolver. An
``ambiguous`` deadline is stored with **no date**, and the interface shows
the sender's phrase as a question. The answer comes from the user, and the
row becomes ``user_confirmed`` or ``user_corrected`` -- which means it can
never again be mistaken for something a model worked out.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import AuthContext, require_csrf
from app.core.clock import get_clock
from app.core.logging import get_logger

router = APIRouter(tags=["tasks"])
log = get_logger(__name__)

TaskFilter = Literal["all", "today", "upcoming", "completed"]


class TaskOut(BaseModel):
    id: UUID
    title: str
    status: str
    #: user | ai_suggestion | sender_request. The three are visibly
    #: different on screen: a task the user wrote and a task extracted
    #: from someone else's email are not the same kind of thing.
    origin: str
    due_at: datetime | None
    notes: str | None
    remind_at: datetime | None
    confirmed_at: datetime | None
    completed_at: datetime | None
    thread_id: UUID | None
    #: For the "link back to source email" requirement.
    thread_subject: str | None = None
    source_sender: str | None = None
    action_item_id: UUID | None = None
    deadline_id: UUID | None = None
    #: What the sender wrote, when this task came from a deadline. Shown
    #: alongside the date so the user can see where it came from.
    deadline_phrase: str | None = None
    deadline_resolution: str | None = None


class TaskPage(BaseModel):
    items: list[TaskOut]
    counts: dict[str, int]


class SuggestionOut(BaseModel):
    """An extracted action item that is not yet a task."""

    action_item_id: UUID
    description: str
    owner: str
    #: stated | inferred. Never conflated, including here.
    source: str
    thread_id: UUID
    thread_subject: str | None
    sender: str | None
    quote: str | None = None


class AmbiguousDeadlineOut(BaseModel):
    """A deadline that renders as a question, never as a date."""

    deadline_id: UUID
    #: The sender's words. This is what the question quotes.
    raw_phrase: str
    date_type: str
    confidence_band: str
    thread_id: UUID
    thread_subject: str | None
    sender: str | None
    message_sent_at: datetime | None
    #: Dates the user can pick in one click, computed deterministically
    #: from the message's send date. Offered, never assumed.
    options: list[date] = Field(default_factory=list)


class CreateTask(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None
    notes: str | None = None
    thread_id: UUID | None = None


class UpdateTask(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["pending", "done", "dismissed"] | None = None
    due_at: datetime | None = None
    clear_due: bool = False
    notes: str | None = None
    remind_at: datetime | None = None


class ResolveDeadline(BaseModel):
    #: The date the user chose. Required: resolving a deadline to nothing
    #: is dismissing it, which is a different route.
    chosen_date: date
    #: True when the user is correcting a date Maail had resolved, false
    #: when answering a question it asked. Both end up as the user's,
    #: and the two are recorded separately because one of them is a
    #: Maail mistake and counting those matters.
    was_wrong: bool = False


_SELECT_TASK = """
    SELECT t.id, t.title, t.status, t.origin, t.due_at, t.notes, t.remind_at,
           t.confirmed_at, t.completed_at, t.thread_id, th.subject,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.thread_id AND NOT m.is_from_user
               AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1),
           t.action_item_id, t.deadline_id, d.raw_phrase, d.resolution_status::text
      FROM tasks t
      LEFT JOIN email_threads th ON th.id = t.thread_id
      LEFT JOIN deadlines d ON d.id = t.deadline_id
"""

_COUNTS = text(
    """
    SELECT
      count(*) FILTER (WHERE status = 'pending'),
      count(*) FILTER (WHERE status = 'pending'
                         AND due_at IS NOT NULL
                         AND due_at < date_trunc('day', now()) + interval '1 day'),
      count(*) FILTER (WHERE status = 'pending'
                         AND due_at >= date_trunc('day', now()) + interval '1 day'),
      count(*) FILTER (WHERE status = 'done')
      FROM tasks
    """
)

_SUGGESTIONS = text(
    """
    SELECT a.id, a.description, a.owner, a.source, a.thread_id, th.subject,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = a.thread_id AND NOT m.is_from_user
               AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1),
           a.message_id, a.evidence_char_start, a.evidence_char_end
      FROM action_items a
      JOIN email_threads th ON th.id = a.thread_id
     WHERE a.status = 'open'
       AND a.created_by = 'agent'
       AND a.owner IN ('user','unclear')
       AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.action_item_id = a.id)
     ORDER BY (a.source = 'stated') DESC, a.created_at DESC
     LIMIT 50
    """
)

_AMBIGUOUS = text(
    """
    SELECT d.id, d.raw_phrase, d.date_type::text, d.confidence_band,
           d.thread_id, th.subject, m.from_email, m.sent_at
      FROM deadlines d
      JOIN email_threads th ON th.id = d.thread_id
      JOIN email_messages m ON m.id = d.message_id
     WHERE d.resolution_status = 'ambiguous'
       AND d.superseded_by IS NULL
       AND d.is_for_user
     ORDER BY m.sent_at DESC
     LIMIT 25
    """
)


def _row_to_task(row: object) -> TaskOut:
    data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
    return TaskOut(
        id=data[0],
        title=str(data[1]),
        status=str(data[2]),
        origin=str(data[3]),
        due_at=data[4],
        notes=data[5],
        remind_at=data[6],
        confirmed_at=data[7],
        completed_at=data[8],
        thread_id=data[9],
        thread_subject=data[10],
        source_sender=data[11],
        action_item_id=data[12],
        deadline_id=data[13],
        deadline_phrase=data[14],
        deadline_resolution=data[15],
    )


@router.get("/tasks", response_model=TaskPage, summary="Screen 09's four tabs")
async def list_tasks(
    auth: AuthContext,
    filter: TaskFilter = Query("all"),
) -> TaskPage:
    """Four filters, all of them SQL. No model decides what is due today."""
    where = {
        "all": "WHERE t.status = 'pending'",
        "today": (
            "WHERE t.status = 'pending' AND t.due_at IS NOT NULL "
            "AND t.due_at < date_trunc('day', now()) + interval '1 day'"
        ),
        "upcoming": (
            "WHERE t.status = 'pending' AND t.due_at >= date_trunc('day', now()) + interval '1 day'"
        ),
        "completed": "WHERE t.status = 'done'",
    }[filter]

    order = (
        "ORDER BY t.completed_at DESC NULLS LAST"
        if filter == "completed"
        else "ORDER BY t.due_at ASC NULLS LAST, t.created_at DESC"
    )

    rows = (await auth.session.execute(text(f"{_SELECT_TASK} {where} {order} LIMIT 200"))).all()
    counts = (await auth.session.execute(_COUNTS)).one()

    return TaskPage(
        items=[_row_to_task(row) for row in rows],
        counts={
            "all": int(counts[0] or 0),
            "today": int(counts[1] or 0),
            "upcoming": int(counts[2] or 0),
            "completed": int(counts[3] or 0),
        },
    )


@router.get(
    "/tasks-suggestions",
    response_model=list[SuggestionOut],
    summary="Extracted action items that are not yet tasks",
)
async def list_suggestions(auth: AuthContext) -> list[SuggestionOut]:
    """Suggestions, kept apart from commitments.

    These are things an agent read in an email. Until the user accepts
    one, it is Maail's reading of their obligations and not their task
    list, and the screen shows it in its own section saying so.
    """
    from app.modules.harness.evidence import load_resolver

    rows = (await auth.session.execute(_SUGGESTIONS)).all()
    out: list[SuggestionOut] = []

    # One resolver per thread, so a page of suggestions from four threads
    # is four loads rather than fifty.
    resolvers: dict[UUID, object] = {}
    for row in rows:
        thread_id = row[4]
        if thread_id not in resolvers:
            resolvers[thread_id] = await load_resolver(auth.session, thread_id)
        resolver = resolvers[thread_id]
        span = resolver.resolve(  # type: ignore[attr-defined]
            {"message_id": row[7], "char_start": row[8], "char_end": row[9]}
        )
        out.append(
            SuggestionOut(
                action_item_id=row[0],
                description=str(row[1]),
                owner=str(row[2]),
                source=str(row[3]),
                thread_id=thread_id,
                thread_subject=row[5],
                sender=row[6],
                quote=span.quote if span else None,
            )
        )
    return out


@router.get(
    "/deadlines-ambiguous",
    response_model=list[AmbiguousDeadlineOut],
    summary="Deadlines that need the user to say which date",
)
async def list_ambiguous(auth: AuthContext) -> list[AmbiguousDeadlineOut]:
    """The resolver's queue.

    Each row renders as the sender's own phrase, quoted, with a question.
    The options are computed from the message's send date by code -- the
    candidate days a phrase like "Friday" could mean -- and offered, not
    chosen.
    """
    rows = (await auth.session.execute(_AMBIGUOUS)).all()
    return [
        AmbiguousDeadlineOut(
            deadline_id=row[0],
            raw_phrase=str(row[1]),
            date_type=str(row[2]),
            confidence_band=str(row[3]),
            thread_id=row[4],
            thread_subject=row[5],
            sender=row[6],
            message_sent_at=row[7],
            options=_candidate_days(str(row[1]), row[7]),
        )
        for row in rows
    ]


def _candidate_days(phrase: str, sent_at: datetime | None) -> list[date]:
    """Which days the phrase might mean, from the send date. Deterministic.

    For a weekday phrase, the two nearest matching days -- which is
    exactly the ambiguity "by Friday" has when it was sent on a Friday.
    No model, and no preference between them: that is the user's to give.
    """
    if sent_at is None:
        return []

    from datetime import timedelta

    weekdays = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    lowered = phrase.lower()
    target = next((index for index, name in enumerate(weekdays) if name in lowered), None)
    if target is None:
        return []

    anchor = sent_at.date()
    ahead = (target - anchor.weekday()) % 7
    first = anchor + timedelta(days=ahead or 7)
    if ahead == 0:
        # Sent on the day it names: today and next week are both
        # plausible readings, which is the ambiguity itself.
        return [anchor, first]
    return [first, first + timedelta(days=7)]


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
    summary="Create a task, optionally from an email",
)
async def create_task(body: CreateTask, auth: AuthContext) -> TaskOut:
    """A task the user wrote. Confirmed by the act of writing it."""
    now = get_clock().now()
    task_id = await auth.session.scalar(
        text(
            """
            INSERT INTO tasks (user_id, title, thread_id, due_at, notes, origin,
                               confirmed_at)
            VALUES (:user_id, :title, :thread_id, :due_at, :notes, 'user', :now)
            RETURNING id
            """
        ),
        {
            "user_id": str(auth.user_id),
            "title": body.title,
            "thread_id": str(body.thread_id) if body.thread_id else None,
            "due_at": body.due_at,
            "notes": body.notes,
            "now": now,
        },
    )
    return await _read_task(auth, UUID(str(task_id)))


@router.post(
    "/action-items/{action_item_id}/confirm",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
    summary="Accept an extracted action item as a task",
)
async def confirm_suggestion(action_item_id: UUID, auth: AuthContext) -> TaskOut:
    """The moment a suggestion becomes a commitment.

    ``confirmed_at`` is set here and only here for an AI-origin task. A
    task row with ``origin = 'ai_suggestion'`` and no ``confirmed_at``
    would be Maail having decided something on the user's behalf, which
    is what the column exists to make impossible to do by accident.
    """
    row = (
        await auth.session.execute(
            text(
                """
                SELECT a.description, a.thread_id,
                       (SELECT d.id FROM deadlines d
                         WHERE d.thread_id = a.thread_id
                           AND d.superseded_by IS NULL
                           AND d.is_for_user
                           AND d.normalized_date IS NOT NULL
                         ORDER BY d.normalized_date LIMIT 1)
                  FROM action_items a
                 WHERE a.id = :id AND a.status = 'open'
                """
            ),
            {"id": str(action_item_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such open action item")

    deadline_id = row[2]
    now = get_clock().now()
    task_id = await auth.session.scalar(
        text(
            """
            INSERT INTO tasks (user_id, title, thread_id, action_item_id, deadline_id,
                               due_at, origin, confirmed_at)
            VALUES (:user_id, :title, :thread_id, :action_item_id, :deadline_id,
                    (SELECT (d.normalized_date + coalesce(d.normalized_time, time '17:00'))
                             AT TIME ZONE coalesce(d.timezone, 'UTC')
                       FROM deadlines d WHERE d.id = :deadline_id),
                    'ai_suggestion', :now)
            ON CONFLICT (action_item_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "user_id": str(auth.user_id),
            "title": str(row[0])[:300],
            "thread_id": str(row[1]),
            "action_item_id": str(action_item_id),
            "deadline_id": str(deadline_id) if deadline_id else None,
            "now": now,
        },
    )
    if task_id is None:
        # Already confirmed. Idempotent rather than an error: the user
        # clicked twice and both clicks meant the same thing.
        existing = await auth.session.scalar(
            text("SELECT id FROM tasks WHERE action_item_id = :id"),
            {"id": str(action_item_id)},
        )
        return await _read_task(auth, UUID(str(existing)))

    return await _read_task(auth, UUID(str(task_id)))


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_csrf)],
    summary="Complete a task, change its date, or add notes",
)
async def update_task(task_id: UUID, body: UpdateTask, auth: AuthContext) -> TaskOut:
    sets: list[str] = []
    params: dict[str, object] = {"id": str(task_id)}

    if body.title is not None:
        sets.append("title = :title")
        params["title"] = body.title
    if body.status is not None:
        sets.append("status = :status")
        params["status"] = body.status
        sets.append("completed_at = CASE WHEN :status = 'done' THEN now() ELSE NULL END")
    if body.clear_due:
        sets.append("due_at = NULL")
    elif body.due_at is not None:
        sets.append("due_at = :due_at")
        params["due_at"] = body.due_at
    if body.notes is not None:
        sets.append("notes = :notes")
        params["notes"] = body.notes
    if body.remind_at is not None:
        sets.append("remind_at = :remind_at")
        params["remind_at"] = body.remind_at

    if not sets:
        return await _read_task(auth, task_id)

    updated = await auth.session.scalar(
        # The suppression below is justified: every element of `sets` is a
        # literal written above, and each value travels as a bound
        # parameter. No part of the request body reaches the SQL text.
        text(f"UPDATE tasks SET {', '.join(sets)} WHERE id = :id RETURNING id"),  # noqa: S608
        params,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such task")
    return await _read_task(auth, task_id)


@router.post(
    "/deadlines/{deadline_id}/resolve",
    dependencies=[Depends(require_csrf)],
    summary="Answer the question an ambiguous deadline asked",
)
async def resolve_deadline(
    deadline_id: UUID, body: ResolveDeadline, auth: AuthContext
) -> dict[str, object]:
    """The user supplies the date. It stops being an estimate.

    ``user_confirmed`` and ``user_corrected`` are different stories and
    stored as such: one is Maail asking and being answered, the other is
    Maail having been wrong. Only the second is a mistake worth counting,
    and merging them would hide the rate.
    """
    row = (
        await auth.session.execute(
            text(
                """
                SELECT thread_id, raw_phrase, normalized_date, resolution_status::text
                  FROM deadlines WHERE id = :id AND superseded_by IS NULL
                """
            ),
            {"id": str(deadline_id)},
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deadline")

    new_status = "user_corrected" if body.was_wrong else "user_confirmed"
    await auth.session.execute(
        text(
            """
            UPDATE deadlines
               SET normalized_date = :chosen,
                   resolution_status = CAST(:status AS date_resolution),
                   confidence_band = 'high'
             WHERE id = :id
            """
        ),
        {"id": str(deadline_id), "chosen": body.chosen_date, "status": new_status},
    )

    # Recorded as a correction, like every other one. This is the audit
    # trail for why a date is what it is, and the raw material for
    # noticing that relative dates from one sender are always wrong.
    await auth.session.execute(
        text(
            """
            INSERT INTO user_overrides (user_id, thread_id, field, old_value, new_value)
            VALUES (:user_id, :thread_id, 'deadline',
                    CAST(:old AS jsonb), CAST(:new AS jsonb))
            """
        ),
        {
            "user_id": str(auth.user_id),
            "thread_id": str(row[0]),
            "old": _json({"date": str(row[2]) if row[2] else None, "status": row[3]}),
            "new": _json({"date": str(body.chosen_date), "status": new_status}),
        },
    )

    # Any task already made from this deadline follows the new date.
    await auth.session.execute(
        text(
            """
            UPDATE tasks
               SET due_at = (:chosen::date + time '17:00') AT TIME ZONE 'UTC'
             WHERE deadline_id = :id AND status = 'pending'
            """
        ),
        {"id": str(deadline_id), "chosen": body.chosen_date},
    )

    log.info(
        "deadline.resolved_by_user",
        deadline_id=str(deadline_id),
        was_wrong=body.was_wrong,
    )
    return {
        "deadline_id": str(deadline_id),
        "raw_phrase": str(row[1]),
        "normalized_date": str(body.chosen_date),
        "resolution_status": new_status,
    }


def _json(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload)


async def _read_task(auth: AuthContext, task_id: UUID) -> TaskOut:
    row = (
        await auth.session.execute(text(f"{_SELECT_TASK} WHERE t.id = :id"), {"id": str(task_id)})
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such task")
    return _row_to_task(row)
