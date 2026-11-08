"""Phase 1 blocking gate: cross-tenant account access is rejected.

Phase 0 proved RLS holds at the database. This proves the HTTP surface built
on top of it holds too -- which is a separate claim, because a handler that
takes an id from the URL can read the wrong row without RLS ever being wrong.

Two users sign in through two independent clients, exactly as two browsers
would, and then each one is pointed at the other's account id.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import csrf_headers, sign_in

pytestmark = [pytest.mark.security, pytest.mark.integration]


@pytest.fixture
async def two_signed_in_users(app_engine: object, clean_database: None):
    """Two browsers, two Google identities, two sessions."""
    from app.api.v1.auth import oauth_client
    from app.main import app
    from tests.fakes import FakeOAuthClient

    alice_google = FakeOAuthClient(
        email="alice@example.com",
        name="Alice",
        access_token="alice-access",
        refresh_token="alice-refresh",
    )
    bob_google = FakeOAuthClient(
        email="bob@example.com",
        name="Bob",
        access_token="bob-access",
        refresh_token="bob-refresh",
    )

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        ) as alice,
        AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        ) as bob,
    ):
        app.dependency_overrides[oauth_client] = lambda: alice_google
        await sign_in(alice)
        app.dependency_overrides[oauth_client] = lambda: bob_google
        await sign_in(bob)
        try:
            yield alice, bob
        finally:
            app.dependency_overrides.pop(oauth_client, None)


async def account_id_of(client: AsyncClient) -> str:
    response = await client.get("/api/v1/accounts")
    assert response.status_code == 200, response.text
    accounts = response.json()
    assert len(accounts) == 1
    return accounts[0]["id"]


async def test_each_user_sees_only_their_own_account(two_signed_in_users: tuple) -> None:
    alice, bob = two_signed_in_users

    alice_accounts = (await alice.get("/api/v1/accounts")).json()
    bob_accounts = (await bob.get("/api/v1/accounts")).json()

    assert [a["email"] for a in alice_accounts] == ["alice@example.com"]
    assert [a["email"] for a in bob_accounts] == ["bob@example.com"]


async def test_reconnecting_someone_elses_account_is_a_404(two_signed_in_users: tuple) -> None:
    """404, not 403.

    403 would confirm the id exists and belongs to somebody. The same answer
    for "not yours" and "never existed" tells an attacker nothing.
    """
    alice, bob = two_signed_in_users
    bob_account = await account_id_of(bob)

    response = await alice.post(
        f"/api/v1/accounts/{bob_account}/reconnect", headers=csrf_headers(alice)
    )
    assert response.status_code == 404


async def test_disconnecting_someone_elses_account_is_a_404(two_signed_in_users: tuple) -> None:
    alice, bob = two_signed_in_users
    bob_account = await account_id_of(bob)

    response = await alice.request(
        "DELETE", f"/api/v1/accounts/{bob_account}", headers=csrf_headers(alice)
    )
    assert response.status_code == 404

    # And Bob's account is untouched.
    still_there = (await bob.get("/api/v1/accounts")).json()
    assert still_there[0]["status"] == "active"


async def test_an_unauthenticated_caller_gets_401_not_an_empty_list(
    api: AsyncClient,
) -> None:
    """An empty list would read as "you have no accounts"."""
    response = await api.get("/api/v1/accounts")
    assert response.status_code == 401


async def test_the_credentials_table_is_scoped_too(
    two_signed_in_users: tuple, app_engine: AsyncEngine
) -> None:
    """Belt and braces, at the layer below the handlers.

    Even armed as Alice, a query with no WHERE clause returns only her row.
    """
    alice, _bob = two_signed_in_users

    alice_id = (await alice.get("/api/v1/auth/session")).json()["user"]["id"]

    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": alice_id}
            )
            rows = (await conn.execute(text("SELECT user_id FROM oauth_credentials"))).all()

    assert [str(row[0]) for row in rows] == [alice_id]
