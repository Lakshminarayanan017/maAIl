"""Connected accounts and their encrypted credentials.

``OAuthCredential`` holds ciphertext and a wrapped data key. There is no
property, no hybrid attribute and no ``__repr__`` that will hand you a token;
decryption is an explicit call in ``app.core.crypto``, so a token appearing
somewhere it should not is a line of code someone wrote on purpose.

DDL of record: docs/architecture/02-lld-data-model.md §1.
"""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, utcnow_column


class AccountStatus(str, enum.Enum):
    """The lifecycle of a connection.

    ``reauth_required`` is a first-class state, not an error. A Testing-mode
    refresh token expires after about seven days, so weekly re-authorisation
    is the normal case this product was designed around (gap A3). Sync fails
    soft into this state rather than raising.
    """

    connecting = "connecting"
    active = "active"
    reauth_required = "reauth_required"
    disconnected = "disconnected"
    error = "error"


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (
        CheckConstraint("provider IN ('gmail')", name="provider_supported"),
        UniqueConstraint(
            "user_id", "provider", "provider_account_email", name="uq_connected_accounts_identity"
        ),
        Index("ix_connected_accounts_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        SAEnum(
            AccountStatus, name="account_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=AccountStatus.connecting,
    )
    granted_scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)

    history_cursor: Mapped[str | None] = mapped_column(Text)
    history_cursor_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    initial_sync_total: Mapped[int | None] = mapped_column(Integer)
    initial_sync_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delta_sync_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = utcnow_column()
    disconnected_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    credential: Mapped[OAuthCredential | None] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"

    account_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("connected_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    access_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Which key encryption key wrapped ``dek_wrapped``. Rotation reads the old
    #: version and writes the new one; without this column it cannot happen.
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)

    access_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    #: Known ahead of time in Testing mode, so the UI can warn before the
    #: token dies rather than after a sync fails.
    refresh_expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    updated_at: Mapped[datetime] = utcnow_column()

    account: Mapped[ConnectedAccount] = relationship(back_populates="credential")
