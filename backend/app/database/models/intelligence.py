"""Stored intelligence: what an agent concluded about a thread.

A status per capability, never one global boolean. A thread whose summary
is ready and whose deadline extraction failed has to be able to say
exactly that, or the interface has to lie in one direction (gap C4).

``priority_computed_at`` is here so decay can be applied at query time. A
thread urgent on Monday is noise by Friday, and rewriting the stored
judgement to say so would destroy the record of why it was ever urgent
(gap E3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column


class ThreadIntelligence(Base):
    __tablename__ = "thread_intelligence"

    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[str | None] = mapped_column(Text)
    #: 'user_rule' | 'agent' | 'user_override'. The three stay visibly
    #: different on screen; a correction must never look like a guess.
    category_source: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    priority_reason: Mapped[str | None] = mapped_column(Text)
    priority_computed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    needs_reply: Mapped[bool | None] = mapped_column(Boolean)
    is_technical: Mapped[bool | None] = mapped_column(Boolean)
    routed_agents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    status_summary: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    status_deadline: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    status_actions: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    status_developer: Mapped[str] = mapped_column(Text, nullable=False, default="not_applicable")
    status_opportunity: Mapped[str] = mapped_column(Text, nullable=False, default="not_applicable")

    #: Which version of the thread this judgement was made from. Compared
    #: against the thread's current version to detect staleness.
    computed_from_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = utcnow_column()


class UserOverride(Base):
    """A correction. Kept, because it is both the audit trail and the
    raw material for suggesting a rule."""

    __tablename__ = "user_overrides"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = utcnow_column()
