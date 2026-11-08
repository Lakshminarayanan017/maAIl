"""Shared fixtures.

Two things matter here. The clock is frozen for every test, so a suite's
answers do not change on Friday. And anything needing Postgres skips loudly
rather than failing confusingly when the database is down — ``arch`` and
``unit`` must stay runnable with nothing but Python installed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone

import pytest

os.environ.setdefault("MAAIL_ENV", "test")

# Windows defaults to the Proactor loop, whose transports complain loudly
# when they are finalised after their loop has closed. Selector behaves.
if sys.platform == "win32":  # pragma: no cover - platform specific
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: A fixed, unremarkable Wednesday. Relative-date tests resolve against this.
FROZEN_NOW = datetime(2026, 3, 11, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[object]:
    """Every test gets a stopped clock unless it asks to advance one."""
    from app.core.clock import FrozenClock, SystemClock, set_clock

    clock = FrozenClock(FROZEN_NOW)
    set_clock(clock)
    yield clock
    set_clock(SystemClock())


@pytest.fixture(autouse=True)
async def _fresh_engine_per_test() -> AsyncIterator[None]:
    """Dispose the application engine between tests.

    Each test gets its own event loop, and the module-level engine pools
    connections bound to whichever loop created them. Reusing one across
    loops is the actual bug behind the "Exception ignored in __del__" noise,
    not just the noise.
    """
    yield
    from app.database.engine import dispose_engine

    await dispose_engine()


@pytest.fixture(scope="session")
def database_url() -> str:
    from app.core.config import get_settings

    return get_settings().app_database_url


@pytest.fixture(scope="session")
def owner_url() -> str:
    from app.core.config import get_settings

    return get_settings().owner_database_url


#: Probed once per URL per session. Without the cache every database-backed
#: test pays the connect timeout again, which turns "Postgres is down" into a
#: minute of waiting instead of a line of output.
_REACHABILITY: dict[str, str | None] = {}


async def _reachable(url: str) -> str | None:
    """None if the database answered, otherwise why it did not."""
    if url in _REACHABILITY:
        return _REACHABILITY[url]

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        url,
        echo=False,
        pool_pre_ping=False,
        connect_args={"timeout": 3, "statement_cache_size": 0},
    )
    reason: str | None = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()

    _REACHABILITY[url] = reason
    return reason


@pytest.fixture
async def app_engine(database_url: str) -> AsyncIterator[object]:
    """An engine on the **application** role. Subject to RLS.

    Skips when Postgres is not running, naming the reason, because a silent
    skip on the tenancy test is worse than a failure.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    reason = await _reachable(database_url)
    if reason is not None:
        pytest.skip(f"Postgres unreachable as the application role — {reason}")

    engine = create_async_engine(
        database_url,
        echo=False,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def owner_engine(owner_url: str) -> AsyncIterator[object]:
    """An engine on the owner role, for arranging fixtures RLS would block."""
    from sqlalchemy.ext.asyncio import create_async_engine

    reason = await _reachable(owner_url)
    if reason is not None:
        pytest.skip(f"Postgres unreachable as the owner role — {reason}")

    engine = create_async_engine(owner_url, echo=False)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded_tenants(owner_engine: object) -> AsyncIterator[tuple[object, object]]:
    """Two real users, A and B, for the isolation proof."""
    from app.database.seed import _UPSERT, FIXTURES, USER_A, USER_B

    async with owner_engine.begin() as conn:  # type: ignore[attr-defined]
        for user_id, email, name, tz in FIXTURES:
            await conn.execute(
                _UPSERT, {"id": user_id, "email": email, "name": name, "timezone": tz}
            )
    yield USER_A, USER_B


# ---------------------------------------------------------------------------
# phase 1: the HTTP surface, with a Google that does what the test says
# ---------------------------------------------------------------------------
@pytest.fixture
async def clean_database(owner_engine: object) -> AsyncIterator[None]:
    """Start each API test from an empty set of user rows.

    TRUNCATE as the owner, because RLS would otherwise hide half of what
    needs clearing. ``users`` cascades to everything phase 1 writes.
    """
    from sqlalchemy import text as _text

    async with owner_engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(_text("TRUNCATE users, oauth_states RESTART IDENTITY CASCADE"))
    yield
    async with owner_engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(_text("TRUNCATE users, oauth_states RESTART IDENTITY CASCADE"))


@pytest.fixture
def fake_oauth() -> object:
    from tests.fakes import FakeOAuthClient

    return FakeOAuthClient()


@pytest.fixture
async def api(
    app_engine: object, clean_database: None, fake_oauth: object
) -> AsyncIterator[object]:
    """An HTTP client against the real app, with the real database.

    Redirects are not followed: the OAuth callback's redirect target and the
    cookies it sets are most of what these tests are checking.
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.v1.auth import oauth_client
    from app.main import app

    app.dependency_overrides[oauth_client] = lambda: fake_oauth
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(oauth_client, None)
