"""Seeded development fixtures. Run through ``./scripts/db.sh seed``.

These are two real rows in a development database, not placeholder data in the
running application. They exist so the tenancy test has two tenants to prove
isolation between, and so phase 1 has an account to attach to.

Fixed UUIDs on purpose: a test that asserts "A sees none of B" needs to name A
and B, and a deterministic fixture is the difference between a failing test and
a flaky one.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

USER_A = UUID("00000000-0000-4000-8000-00000000000a")
USER_B = UUID("00000000-0000-4000-8000-00000000000b")

FIXTURES: tuple[tuple[UUID, str, str, str], ...] = (
    (USER_A, "a@maail.test", "Tenant A", "Asia/Kolkata"),
    (USER_B, "b@maail.test", "Tenant B", "America/New_York"),
)

_UPSERT = text(
    """
    INSERT INTO users (id, email, name, timezone)
    VALUES (:id, :email, :name, :timezone)
    ON CONFLICT (id) DO UPDATE
      SET email = excluded.email,
          name = excluded.name,
          timezone = excluded.timezone
    """
)


async def seed() -> list[UUID]:
    """Idempotent. Connects as the owner, because RLS would block these writes."""
    engine = create_async_engine(settings.owner_database_url, echo=False)
    try:
        async with engine.begin() as conn:
            for user_id, email, name, tz in FIXTURES:
                await conn.execute(
                    _UPSERT, {"id": user_id, "email": email, "name": name, "timezone": tz}
                )
    finally:
        await engine.dispose()
    return [row[0] for row in FIXTURES]


def main() -> None:
    import sys

    ids = asyncio.run(seed())
    sys.stdout.write(f"seeded {len(ids)} users: {', '.join(str(i) for i in ids)}\n")


if __name__ == "__main__":
    main()
