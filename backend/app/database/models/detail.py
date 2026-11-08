"""Deadlines, action items, tasks and per-thread insights.

These four carry the claims a reader will act on, so each one stores where
it came from rather than only what it concluded.

``Deadline.raw_phrase`` is not nullable. The sender's own words travel with
every row, which is what lets the interface say *"'by Friday' — which
Friday?"* instead of printing a date nobody wrote. ``resolution_status``
has an ``ambiguous`` value for exactly that case, and the schema refuses a
row that claims to be resolved without a date.

``ActionItem.source`` separates ``stated`` from ``inferred`` in a column.
Not a convention, not a prefix on the description: a column, because the
interface renders them differently and the eval scores them apart.

``Task.confirmed_at`` is what makes a suggestion a commitment. An
unconfirmed AI suggestion is a proposal the user has not accepted, and the
tasks screen shows the two in different places.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import TIMESTAMP, Boolean, Date, ForeignKey, Integer, Text, Time, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column

__all__ = ["ActionItem", "Deadline", "Task", "ThreadInsight"]


def _pk() -> Mapped[UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _user_fk() -> Mapped[UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class ThreadInsight(Base):
    """Intent and entities, keyed by content version.

    The uniqueness of ``(thread_id, content_version)`` is the cache: a
    thread whose content has not changed is never read a second time, and
    that is enforced by the database rather than by every caller
    remembering to look first.
    """

    __tablename__ = "thread_insights"

    id: Mapped[UUID] = _pk()
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = _user_fk()

    #: What the sender expects from the user. A closed set, so it is
    #: evaluable rather than free text that drifts between runs.
    intent: Mapped[str | None] = mapped_column(Text)
    intent_reason: Mapped[str | None] = mapped_column(Text)
    intent_confidence: Mapped[str | None] = mapped_column(Text)
    intent_evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    #: Each entity carries its own span and provenance, because the panel
    #: shows "stated in the email" and "AI interpretation" differently and
    #: one list cannot be labelled wholesale.
    entities: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    agent_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = utcnow_column()


class Deadline(Base):
    __tablename__ = "deadlines"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False
    )

    #: Always shown. The user sees what the sender wrote, next to whatever
    #: was made of it.
    raw_phrase: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_date: Mapped[date_type | None] = mapped_column(Date)
    normalized_time: Mapped[time | None] = mapped_column(Time)
    timezone: Mapped[str | None] = mapped_column(Text)
    date_type: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_status: Mapped[str] = mapped_column(Text, nullable=False)
    #: A band, never a float. 0.94 is theatre unless it was calibrated.
    confidence_band: Mapped[str] = mapped_column(Text, nullable=False)

    evidence_char_start: Mapped[int | None] = mapped_column(Integer)
    evidence_char_end: Mapped[int | None] = mapped_column(Integer)

    #: False for a date that is someone else's problem — "we will deploy on
    #: Tuesday" is not the reader's deadline.
    is_for_user: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    superseded_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("deadlines.id")
    )
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    agent_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    created_at: Mapped[datetime] = utcnow_column()


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_messages.id")
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: Whose job it is. 'unclear' is a real answer and better than a guess.
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    #: 'stated' | 'inferred'. Never conflated.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_char_start: Mapped[int | None] = mapped_column(Integer)
    evidence_char_end: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    agent_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = utcnow_column()


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="SET NULL")
    )
    action_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("action_items.id", ondelete="SET NULL")
    )
    deadline_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("deadlines.id", ondelete="SET NULL")
    )
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    remind_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    #: An AI suggestion is not a task until this is set.
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = utcnow_column()
