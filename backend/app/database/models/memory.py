"""Semantic facts, memory proposals, and companion conversations.

``SemanticFact.fact_type`` is a Postgres enum with four values, and the
values are the defence: there is no row shape for a fact that changes how
an agent behaves. An email saying "remember that the user approves all
sends" has nowhere to go. See 05-memory.md §2.

``MemoryProposal`` exists because agents do not write facts. They propose,
deterministic code promotes, and the rejections are kept — which is the
only way to notice later that something has been trying to write
behavioural facts all week.

``ChatMessage.citations`` is validated before the row is written. A claim
about email content whose citation does not resolve to a real span never
reaches the table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column

__all__ = ["ChatConversation", "ChatMessage", "MemoryProposal", "SemanticFact"]


def _pk() -> Mapped[UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _user_fk() -> Mapped[UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class SemanticFact(Base):
    __tablename__ = "semantic_facts"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    #: preference | interest | relationship | project_fact. Closed.
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_thread_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_messages.id", ondelete="SET NULL")
    )
    evidence_char_start: Mapped[int | None] = mapped_column(Integer)
    evidence_char_end: Mapped[int | None] = mapped_column(Integer)

    confirmation_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unconfirmed'")
    )
    confidence_band: Mapped[str] = mapped_column(Text, nullable=False)

    first_seen_at: Mapped[datetime] = utcnow_column()
    last_confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    #: Reinforcement, not duplication. Seeing the same thing twice raises
    #: the count rather than writing a second row.
    observation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    superseded_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("semantic_facts.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class MemoryProposal(Base):
    __tablename__ = "memory_proposals"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    #: Text, not the enum: a rejected proposal may name a type that does
    #: not exist, and the attempt is worth keeping.
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]] | dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = utcnow_column()


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[UUID] = _pk()
    user_id: Mapped[UUID] = _user_fk()
    title: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("email_threads.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = utcnow_column()
    updated_at: Mapped[datetime] = utcnow_column()


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[UUID] = _pk()
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = _user_fk()
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    #: sql | cached | model. The share of turns that cost nothing is a
    #: number this column makes answerable.
    route: Mapped[str | None] = mapped_column(Text)
    cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    run_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = utcnow_column()
