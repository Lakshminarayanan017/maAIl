"""``users`` — the only table phase 0 creates.

It carries no ``user_id`` of its own, so it is not covered by the
``tenant_isolation`` policy that every other table gets. Its own policy
compares ``id`` instead. The schema audit in ``tests/arch`` knows about this
one exception and about nothing else.

DDL of record: docs/architecture/02-lld-data-model.md §1.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, Text, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)

    #: Relative dates resolve against the user's day boundary, never the
    #: server's. See 00-gap-analysis.md §2 E2.
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'UTC'"))

    created_at: Mapped[datetime] = utcnow_column()
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
