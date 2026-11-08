"""The feature toggles a user has actually touched.

Absence is the default, deliberately. Defaults live in
``features/registry.py`` where a change is a reviewed diff; writing
seventeen rows at signup to say "yes, the defaults" would pin every
existing user to whatever the defaults were on the day they registered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow_column

__all__ = ["UserFeature"]


class UserFeature(Base):
    __tablename__ = "user_features"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Validated against the feature's own schema before it is written;
    #: unknown keys are dropped rather than stored.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: The staleness watermark a second process probes. See
    #: ``features/service.py``.
    updated_at: Mapped[datetime] = utcnow_column()
