"""The engine and session factory.

The application connects as ``POSTGRES_APP_USER`` — a non-owner role. That is
not a convenience; a table owner is exempt from its own row-level policies
unless the table is FORCEd *and* the connection is not the owner. The owner URL
exists for migrations and is never imported on a request path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def build_engine(url: str | None = None, *, echo: bool | None = None) -> AsyncEngine:
    return create_async_engine(
        url or settings.app_database_url,
        echo=settings.sql_echo if echo is None else echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        # A statement that outlives a request is a resource leak with a nicer
        # name. Bound here rather than per query so nothing can forget.
        connect_args={
            "server_settings": {
                "application_name": "maail-api",
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "jit": "off",
            },
            # asyncpg caches plans per connection; PgBouncer in transaction
            # mode would make that unsafe, so it stays off from the start.
            "statement_cache_size": 0,
        },
    )


engine: AsyncEngine = build_engine()

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def dispose_engine() -> None:
    await engine.dispose()


async def raw_session() -> AsyncIterator[AsyncSession]:
    """A session with **no tenant set**.

    Only for work that touches no user-scoped table — health checks, the
    features catalog. Any user-scoped read through this returns zero rows,
    because ``app_current_user()`` is NULL. That is the intended failure mode:
    empty, not everything.
    """
    async with SessionFactory() as session:
        yield session
