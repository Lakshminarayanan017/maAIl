"""Browser sessions and the OAuth nonce ledger.

Neither model is read on the hot authentication path. ``Session`` rows are
resolved through ``app_resolve_session`` because the lookup happens before a
tenant is known and RLS would return nothing; these classes exist for the
authenticated views -- listing your own sessions, revoking them -- and for
Alembic to see the tables.

DDL of record: migrations/versions/0002_accounts_credentials_sessions.py.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: sha256 of the cookie. The cookie is never stored, so a database dump
    #: does not hand anyone a working session.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = utcnow_column()
    last_seen_at: Mapped[datetime] = utcnow_column()
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class OAuthState(Base):
    """One row per authorization request. Single use, short lived.

    Deliberately holds no identity. It is written before anyone is
    authenticated, so a ``user_id`` here would mean either a user-scoped table
    with no policy or a policy nothing could satisfy. What the flow is for
    travels in the signed, httpOnly flow cookie instead.
    """

    __tablename__ = "oauth_states"
    __table_args__ = (CheckConstraint("purpose IN ('signin', 'reconnect')", name="purpose_known"),)

    state_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = utcnow_column()
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
