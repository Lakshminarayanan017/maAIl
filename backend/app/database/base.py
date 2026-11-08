"""Declarative base and the naming convention.

Constraint names are generated, not hand-written, so an Alembic autogenerate
diff never churns on a name Postgres chose for itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk: Any = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


def utcnow_column(**kwargs: Any) -> Mapped[datetime]:
    """``timestamptz`` defaulted in the database, not in Python.

    A row's creation time is the database's opinion; two app processes with
    drifting clocks must not produce two different notions of "now".
    """
    return mapped_column(
        TIMESTAMP(timezone=True),
        server_default=text("now()"),
        nullable=False,
        **kwargs,
    )
