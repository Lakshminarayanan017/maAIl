"""Liveness, readiness, and a standing check that the tenancy boundary is armed.

``/ready`` does not just ping the database. It asserts that the role the
application is connected as cannot escape row-level security — not a superuser,
no BYPASSRLS, and not the owner of ``users``. A deployment that quietly
connected as the owner would pass every functional test and leak every tenant,
so the check runs where it will be noticed.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import UnscopedSession
from app.core.config import settings
from app.core.logging import get_logger

router = APIRouter(prefix="/health", tags=["health"])
log = get_logger(__name__)

_ROLE_CHECK = text(
    """
    SELECT r.rolsuper      AS is_superuser,
           r.rolbypassrls  AS can_bypass_rls,
           EXISTS (
             SELECT 1 FROM pg_class c
             JOIN pg_roles o ON o.oid = c.relowner
             WHERE c.relname = 'users' AND o.rolname = current_user
           )               AS owns_users
    FROM pg_roles r
    WHERE r.rolname = current_user
    """
)

_RLS_CHECK = text(
    """
    SELECT c.relrowsecurity AS enabled, c.relforcerowsecurity AS forced
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = 'users'
    """
)


class Live(BaseModel):
    status: Literal["ok"] = "ok"
    env: str
    version: str


class TenancyReport(BaseModel):
    role: str
    is_superuser: bool
    can_bypass_rls: bool
    owns_tables: bool
    rls_enabled: bool
    rls_forced: bool

    @property
    def sound(self) -> bool:
        return (
            not self.is_superuser
            and not self.can_bypass_rls
            and not self.owns_tables
            and self.rls_enabled
            and self.rls_forced
        )


class Ready(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    migrations: str | None
    tenancy: TenancyReport
    problems: list[str] = []


@router.get("/live", response_model=Live, summary="Process is up")
async def live() -> Live:
    from app import __version__

    return Live(env=settings.env, version=__version__)


@router.get(
    "/ready",
    response_model=Ready,
    summary="Database reachable, migrations applied, tenancy boundary armed",
    responses={status.HTTP_200_OK: {"description": "Ready, or degraded with reasons"}},
)
async def ready(session: UnscopedSession) -> Ready:
    problems: list[str] = []

    await session.execute(text("SELECT 1"))

    revision = (
        await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    ).scalar()
    if revision is None:
        problems.append("no migration applied")

    roles = (await session.execute(_ROLE_CHECK)).mappings().one()
    rls = (await session.execute(_RLS_CHECK)).mappings().one_or_none()

    tenancy = TenancyReport(
        role=settings.postgres_app_user,
        is_superuser=bool(roles["is_superuser"]),
        can_bypass_rls=bool(roles["can_bypass_rls"]),
        owns_tables=bool(roles["owns_users"]),
        rls_enabled=bool(rls["enabled"]) if rls else False,
        rls_forced=bool(rls["forced"]) if rls else False,
    )

    if tenancy.is_superuser:
        problems.append("application role is a superuser")
    if tenancy.can_bypass_rls:
        problems.append("application role has BYPASSRLS")
    if tenancy.owns_tables:
        problems.append("application role owns its tables — RLS is escapable")
    if not tenancy.rls_enabled:
        problems.append("row level security not enabled on users")
    if not tenancy.rls_forced:
        problems.append("row level security not FORCEd on users")

    if problems:
        log.error("readiness.degraded", problems=problems)

    return Ready(
        status="ok" if not problems else "degraded",
        database=True,
        migrations=revision,
        tenancy=tenancy,
        problems=problems,
    )
