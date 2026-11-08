"""Threads, messages and attachment metadata.

The thread is the unit of meaning. ``provider_thread_id`` is an attribute of
a thread, not its identity, because Gmail splits and regroups threads and
anything keyed on it gets rebuilt whenever it changes its mind (gap A5).

DDL of record: migrations/versions/0003_threads_and_messages.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    REAL,
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utcnow_column


class EmailThread(Base):
    __tablename__ = "email_threads"
    __table_args__ = (
        UniqueConstraint("account_id", "provider_thread_id", name="uq_threads_provider"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: Set when this thread was merged into another. The row stays so that
    #: intelligence derived against it keeps its audit trail.
    merged_into_thread_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id")
    )

    subject: Mapped[str | None] = mapped_column(Text)
    subject_normalized: Mapped[str | None] = mapped_column(Text)
    participant_emails: Mapped[list[str]] = mapped_column(
        ARRAY(CITEXT), nullable=False, default=list
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_labels: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    first_message_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    latest_message_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    #: Bumped on every ingested message. Anything derived from this thread
    #: records the version it was derived at, so staleness is detectable.
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    created_at: Mapped[datetime] = utcnow_column()
    updated_at: Mapped[datetime] = utcnow_column()

    messages: Mapped[list[EmailMessage]] = relationship(
        back_populates="thread", cascade="all, delete-orphan", lazy="selectin"
    )


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "provider_message_id", name="uq_messages_provider"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )

    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: Survives provider re-threading, which the provider's own id does not.
    rfc822_message_id: Mapped[str | None] = mapped_column(Text)
    in_reply_to: Mapped[str | None] = mapped_column(Text)
    references_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    from_email: Mapped[str | None] = mapped_column(CITEXT)
    from_name: Mapped[str | None] = mapped_column(Text)
    to_emails: Mapped[list[str]] = mapped_column(ARRAY(CITEXT), nullable=False, default=list)
    cc_emails: Mapped[list[str]] = mapped_column(ARRAY(CITEXT), nullable=False, default=list)
    subject: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    #: From the Date header: a deadline of "tomorrow" is the sender's.
    sender_tz_offset_min: Mapped[int | None] = mapped_column(Integer)

    snippet: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    #: Phase 3. The largest single lever on token cost.
    body_text_stripped: Mapped[str | None] = mapped_column(Text)
    stripped_ratio: Mapped[float | None] = mapped_column(REAL)

    size_bytes: Mapped[int | None] = mapped_column(Integer)
    is_from_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_labels: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    #: NULL means metadata-only: pass 1 has seen it, pass 2 has not.
    body_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    body_fetch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_fetch_error: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    created_at: Mapped[datetime] = utcnow_column()

    thread: Mapped[EmailThread] = relationship(back_populates="messages")
    attachments: Mapped[list[MessageAttachment]] = relationship(
        back_populates="message", cascade="all, delete-orphan", lazy="selectin"
    )


class MessageAttachment(Base):
    """Metadata only. No content, no parsing, in v1 (gap D6)."""

    __tablename__ = "message_attachments"
    __table_args__ = (
        UniqueConstraint("message_id", "provider_attachment_id", name="uq_attachment_provider"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    provider_attachment_id: Mapped[str | None] = mapped_column(Text)

    message: Mapped[EmailMessage] = relationship(back_populates="attachments")
