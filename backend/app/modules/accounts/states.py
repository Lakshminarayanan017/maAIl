"""The OAuth state ledger: one row per authorization request, used once.

The signed flow cookie already binds a redirect to the browser that started
it. This table adds the property a cookie cannot: a given state is redeemable
exactly once, across tabs, across replays, and after the cookie has been
copied somewhere else.

It runs before authentication, so it holds no identity at all -- not a user,
not an account. What the flow is for travels in the cookie.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.security import OAUTH_FLOW_TTL_SECONDS

_INSERT = text(
    """
    INSERT INTO oauth_states (state_hash, purpose, expires_at)
    VALUES (:state_hash, :purpose, :expires_at)
    """
)

#: One statement, so two simultaneous callbacks cannot both win. The UPDATE
#: takes a row lock; the second one matches nothing because used_at is set.
#:
#: The expiry is compared against the application clock, not the database's
#: now(). The row was written from the application clock, and comparing a
#: timestamp from one clock against another is how a test suite ends up
#: depending on the wall clock agreeing with itself.
_CONSUME = text(
    """
    UPDATE oauth_states
       SET used_at = :now
     WHERE state_hash = :state_hash
       AND used_at IS NULL
       AND expires_at > :now
    RETURNING purpose
    """
)

_PRUNE = text("DELETE FROM oauth_states WHERE expires_at < :before")


@dataclass(frozen=True)
class ConsumedState:
    purpose: str


def hash_state(state: str) -> bytes:
    return hashlib.sha256(state.encode("ascii")).digest()


async def record(session: AsyncSession, *, state: str, purpose: str) -> None:
    await session.execute(
        _INSERT,
        {
            "state_hash": hash_state(state),
            "purpose": purpose,
            "expires_at": get_clock().now() + timedelta(seconds=OAUTH_FLOW_TTL_SECONDS),
        },
    )


async def consume(session: AsyncSession, *, state: str) -> ConsumedState | None:
    """Spend the state, or None if it was unknown, expired or already spent."""
    row = (
        await session.execute(_CONSUME, {"state_hash": hash_state(state), "now": get_clock().now()})
    ).one_or_none()
    return ConsumedState(purpose=row[0]) if row else None


async def prune(session: AsyncSession) -> int:
    """Housekeeping. Called on each start, so the table cannot grow forever."""
    # AsyncSession.execute is typed as returning Result; a DML statement
    # always gives a CursorResult, which is the one that knows rowcount.
    result = cast(
        "CursorResult[Any]",
        await session.execute(_PRUNE, {"before": get_clock().now() - timedelta(days=1)}),
    )
    return result.rowcount or 0
