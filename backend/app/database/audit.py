"""Schema audit — "no user-scoped table without an RLS policy", made executable.

Used by ``./scripts/db.sh verify`` and by ``tests/arch/test_schema_audit.py``.
It inspects the live database rather than the model metadata, because the thing
that leaks tenants is the database as deployed, not the Python as written.

A table is user-scoped if it has a ``user_id`` column. ``users`` is the one
exception: it is scoped by its own ``id``, and is listed explicitly so the
exception cannot be widened by accident.

See docs/architecture/07-harness.md §8.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: Tables scoped by something other than a ``user_id`` column.
SELF_SCOPED: frozenset[str] = frozenset({"users"})

#: Tables that legitimately hold no tenant data, or whose ``user_id`` is
#: nullable because some rows belong to the system rather than a person --
#: a purge job, a system audit line. They still carry a policy; it just
#: has to admit NULL, which is why they are named rather than inferred.
GLOBAL_TABLES: frozenset[str] = frozenset({"alembic_version"})
NULLABLE_TENANT: frozenset[str] = frozenset({"background_jobs", "audit_logs"})

_TABLES = text(
    """
    SELECT c.relname                AS table_name,
           c.relrowsecurity         AS rls_enabled,
           c.relforcerowsecurity    AS rls_forced,
           o.rolname                AS owner,
           EXISTS (
             SELECT 1 FROM information_schema.columns col
             WHERE col.table_schema = 'public'
               AND col.table_name = c.relname
               AND col.column_name = 'user_id'
           )                        AS has_user_id,
           (SELECT count(*) FROM pg_policies p
             WHERE p.schemaname = 'public' AND p.tablename = c.relname)
                                    AS policy_count,
           EXISTS (
             SELECT 1 FROM pg_policies p
             WHERE p.schemaname = 'public' AND p.tablename = c.relname
               AND p.policyname = 'tenant_isolation'
           )                        AS has_tenant_policy
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_roles o ON o.oid = c.relowner
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY c.relname
    """
)

_APP_ROLE = text(
    """
    SELECT rolsuper AS is_superuser, rolbypassrls AS can_bypass_rls
    FROM pg_roles WHERE rolname = :role
    """
)


@dataclass(frozen=True)
class TableReport:
    name: str
    user_scoped: bool
    rls_enabled: bool
    rls_forced: bool
    policy_count: int
    has_tenant_policy: bool
    owner: str

    @property
    def sound(self) -> bool:
        if not self.user_scoped:
            return True
        return self.rls_enabled and self.rls_forced and self.has_tenant_policy


@dataclass
class AuditResult:
    tables: list[TableReport] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        width = max((len(t.name) for t in self.tables), default=5) + 2
        lines = [f"{'table'.ljust(width)}  scoped  rls  force  policies"]
        for t in self.tables:
            mark = "  " if t.sound else "!!"
            lines.append(
                f"{mark}{t.name.ljust(width - 2)}  "
                f"{'yes' if t.user_scoped else ' - ':>6}  "
                f"{'on' if t.rls_enabled else 'OFF':>3}  "
                f"{'on' if t.rls_forced else 'OFF':>5}  "
                f"{t.policy_count:>8}"
            )
        if self.problems:
            lines.append("")
            lines += [f"FAIL  {p}" for p in self.problems]
        return "\n".join(lines)


async def audit_schema(conn: AsyncConnection, *, app_role: str) -> AuditResult:
    result = AuditResult()

    rows = (await conn.execute(_TABLES)).mappings().all()
    if not rows:
        result.problems.append("no tables in public schema — migrations not applied")
        return result

    for row in rows:
        name = row["table_name"]
        if name in GLOBAL_TABLES:
            continue
        user_scoped = bool(row["has_user_id"]) or name in SELF_SCOPED
        report = TableReport(
            name=name,
            user_scoped=user_scoped,
            rls_enabled=bool(row["rls_enabled"]),
            rls_forced=bool(row["rls_forced"]),
            policy_count=int(row["policy_count"]),
            has_tenant_policy=bool(row["has_tenant_policy"]),
            owner=row["owner"],
        )
        result.tables.append(report)

        if not user_scoped:
            continue
        if not report.rls_enabled:
            result.problems.append(f"{name}: row level security not enabled")
        if not report.rls_forced:
            result.problems.append(f"{name}: row level security not FORCEd — owner is exempt")
        if not report.has_tenant_policy:
            # Not "has a policy": an owner-scoped maintenance policy would
            # satisfy that while leaving tenants in one another's rows.
            result.problems.append(f"{name}: no tenant_isolation policy")
        if report.owner == app_role:
            result.problems.append(f"{name}: owned by the application role {app_role}")

    role = (await conn.execute(_APP_ROLE, {"role": app_role})).mappings().one_or_none()
    if role is None:
        result.problems.append(f"application role {app_role} does not exist")
    else:
        if role["is_superuser"]:
            result.problems.append(f"{app_role} is a superuser — RLS does not apply to it")
        if role["can_bypass_rls"]:
            result.problems.append(f"{app_role} has BYPASSRLS")

    return result


async def _run() -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(settings.owner_database_url, echo=False)
    try:
        async with engine.connect() as conn:
            result = await audit_schema(conn, app_role=settings.postgres_app_user)
    finally:
        await engine.dispose()

    import sys

    sys.stdout.write(result.render() + "\n")
    return 0 if result.ok else 1


def main() -> None:
    import asyncio

    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
