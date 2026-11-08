"""Nothing user-scoped answers without a session.

Phase 0 asserted this against a placeholder dependency that always refused.
Phase 1 replaced it with real session resolution, so the assertion moves to
the behaviour that now matters: a request with no session cookie is refused
before any database work happens, and a request with a cookie the server does
not recognise is refused too.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.api.deps import authenticated, current_user_id

pytestmark = pytest.mark.integration


def _probe_app() -> FastAPI:
    probe = FastAPI()

    @probe.get("/guarded")
    async def guarded(user_id: UUID = Depends(current_user_id)) -> dict[str, str]:
        return {"user_id": str(user_id)}

    return probe


def _request(cookies: dict[str, str] | None = None) -> Request:
    headers = []
    if cookies:
        jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", jar.encode()))
    return Request({"type": "http", "method": "GET", "headers": headers, "path": "/"})


async def test_an_endpoint_behind_current_user_id_returns_401() -> None:
    transport = ASGITransport(app=_probe_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/guarded")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Cookie"


async def test_no_cookie_is_refused_before_any_database_work() -> None:
    """The cheap check runs first.

    An unauthenticated request should not cost a connection from the pool,
    which also means this test needs no Postgres to be meaningful.
    """
    generator = authenticated(_request())
    with pytest.raises(HTTPException) as caught:
        await generator.__anext__()
    assert caught.value.status_code == 401


async def test_an_empty_cookie_is_not_a_session() -> None:
    generator = authenticated(_request({"maail_session": ""}))
    with pytest.raises(HTTPException) as caught:
        await generator.__anext__()
    assert caught.value.status_code == 401


async def test_an_unknown_cookie_is_refused(app_engine: object) -> None:
    """A well-formed token the server never issued resolves to nobody."""
    generator = authenticated(_request({"maail_session": "a-token-nobody-issued"}))
    with pytest.raises(HTTPException) as caught:
        await generator.__anext__()
    assert caught.value.status_code == 401
