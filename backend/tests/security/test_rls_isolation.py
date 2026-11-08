"""The phase 0 blocking gate.

> Phase 0 is not complete until a test proves user A's query returns zero of
> user B's rows **with the application's own connection**.
> — docs/architecture/02-lld-data-model.md §8

Every query below runs through ``app_engine``, which connects as
``POSTGRES_APP_USER``. Running these as the owner would pass and prove nothing,
which is exactly the mistake the role split exists to prevent.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.security, pytest.mark.integration]

SET_TENANT = text("SELECT set_config('app.user_id', :user_id, true)")
COUNT_ALL = text("SELECT count(*) FROM users")
SELECT_IDS = text("SELECT id FROM users")


async def test_application_role_cannot_escape_rls(app_engine: AsyncEngine) -> None:
    """Not a superuser, no BYPASSRLS, and not the owner of users.

    Any one of those three would make every assertion below vacuous.
    """
    async with app_engine.connect() as conn:
        role = (
            await conn.execute(
                text(
                    """
                    SELECT r.rolsuper, r.rolbypassrls,
                           EXISTS (
                             SELECT 1 FROM pg_class c
                             JOIN pg_roles o ON o.oid = c.relowner
                             WHERE c.relname = 'users' AND o.rolname = current_user
                           ) AS owns_users
                    FROM pg_roles r WHERE r.rolname = current_user
                    """
                )
            )
        ).one()
        assert role.rolsuper is False, "the application role is a superuser"
        assert role.rolbypassrls is False, "the application role has BYPASSRLS"
        assert role.owns_users is False, "the application role owns users — RLS is escapable"

        forced = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'users'"
                )
            )
        ).one()
        assert forced.relrowsecurity is True
        assert forced.relforcerowsecurity is True


async def test_tenant_a_sees_none_of_tenant_b(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    user_a, user_b = seeded_tenants

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(SET_TENANT, {"user_id": str(user_a)})

            visible = {row[0] for row in (await conn.execute(SELECT_IDS)).all()}
            assert visible == {user_a}, f"tenant A saw {visible}"

            leaked = (
                await conn.execute(
                    text("SELECT count(*) FROM users WHERE id = :other"), {"other": str(user_b)}
                )
            ).scalar()
            assert leaked == 0, "a WHERE clause naming another tenant returned rows"


async def test_no_tenant_means_no_rows(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    """The failure mode is empty, not everything.

    app.user_id unset makes app_current_user() NULL, and ``id = NULL`` is never
    true. A forgotten SET LOCAL therefore returns nothing rather than the whole
    table.
    """
    async with app_engine.connect() as conn:
        assert (await conn.execute(COUNT_ALL)).scalar() == 0


async def test_tenant_does_not_survive_its_transaction(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    """``is_local => true`` is what keeps a pooled connection safe.

    Without it, one request's identity would still be set when the next request
    picked the connection out of the pool.
    """
    user_a, _ = seeded_tenants

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(SET_TENANT, {"user_id": str(user_a)})
            assert (await conn.execute(COUNT_ALL)).scalar() == 1

        # same connection, new transaction, no tenant
        assert (await conn.execute(COUNT_ALL)).scalar() == 0


async def test_tenant_a_cannot_write_tenant_b(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    """USING blocks the read, so the UPDATE matches nothing. No error, no change."""
    user_a, user_b = seeded_tenants

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(SET_TENANT, {"user_id": str(user_a)})
            result = await conn.execute(
                text("UPDATE users SET name = :name WHERE id = :target"),
                {"name": "owned", "target": str(user_b)},
            )
            assert result.rowcount == 0

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(SET_TENANT, {"user_id": str(user_b)})
            name = (
                await conn.execute(
                    text("SELECT name FROM users WHERE id = :id"), {"id": str(user_b)}
                )
            ).scalar()
            assert name == "Tenant B"


async def test_tenant_a_cannot_insert_as_someone_else(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    """WITH CHECK is the half of the policy people forget.

    USING filters what you can see. Without WITH CHECK, A could insert a row
    belonging to B — invisible to A afterwards, and very visible to B.
    """
    user_a, _ = seeded_tenants
    stranger = uuid4()

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(SET_TENANT, {"user_id": str(user_a)})
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": str(stranger), "email": f"{stranger}@maail.test"},
                )
    assert "row-level security" in str(caught.value).lower()


async def test_application_role_cannot_change_the_policy(
    app_engine: AsyncEngine, seeded_tenants: tuple[UUID, UUID]
) -> None:
    """A boundary the application can lift is not a boundary."""
    async with app_engine.connect() as conn:
        for statement in (
            "ALTER TABLE users DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE users NO FORCE ROW LEVEL SECURITY",
            "DROP POLICY tenant_isolation ON users",
            "CREATE POLICY wide_open ON users USING (true)",
        ):
            with pytest.raises(DBAPIError):
                async with conn.begin():
                    await conn.execute(text(statement))
