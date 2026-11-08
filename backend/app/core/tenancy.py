"""Tenancy. One place, one way.

Postgres RLS is the boundary, and the boundary is only armed when
``app.user_id`` is set inside the transaction that runs the query. This module
is the only code allowed to set it. One request dependency and one job wrapper
call in — nothing else.

``SET LOCAL app.user_id = $1`` is not valid Postgres: ``SET`` takes no bind
parameters. ``set_config(..., is_local => true)`` does, so that is what runs.
String-interpolating a user id into a ``SET`` statement would be an injection
site on the one code path that must not have one.

See docs/architecture/02-lld-data-model.md §8 and 01-hld.md §13.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.engine import SessionFactory

_SET_TENANT = text("SELECT set_config('app.user_id', :user_id, true)")
_GET_TENANT = text("SELECT current_setting('app.user_id', true)")

__all__ = ["current_tenant", "set_tenant", "tenant_session"]


async def set_tenant(session: AsyncSession, user_id: UUID) -> None:
    """Arm RLS for the remainder of this transaction.

    ``is_local => true`` ties the setting to the transaction, so a pooled
    connection cannot carry one user's identity into another user's request.
    It therefore requires an open transaction; without one the setting would
    silently evaporate and every query would return nothing.
    """
    if not isinstance(user_id, UUID):
        raise TypeError(f"user_id must be a UUID, got {type(user_id).__name__}")
    if not session.in_transaction():
        raise RuntimeError(
            "set_tenant() needs an open transaction — SET LOCAL outside one has no effect"
        )
    await session.execute(_SET_TENANT, {"user_id": str(user_id)})


async def current_tenant(session: AsyncSession) -> UUID | None:
    """What the database believes the caller is. Used by the RLS tests."""
    raw = (await session.execute(_GET_TENANT)).scalar()
    return UUID(raw) if raw else None


@asynccontextmanager
async def tenant_session(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to one user, for background work.

    The request path gets the same guarantee through ``api.deps``. Workers use
    this, so a job cannot read across tenants by forgetting a WHERE clause.
    """
    async with SessionFactory() as session:
        async with session.begin():
            await set_tenant(session, user_id)
            yield session
