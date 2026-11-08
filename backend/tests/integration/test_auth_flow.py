"""The phase 1 demo, as a test.

> Demo. Sign in, connect a real Gmail account, see it connected. Force token
> expiry; the banner appears and reconnect works.
> (09-execution-plan.md, phase 1)

The only thing faked is Google. Everything else -- the session cookie, the
CSRF check, RLS, the envelope encryption, the account row -- is the real
thing running against a real Postgres.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FROZEN_NOW
from tests.helpers import csrf_headers, sign_in

pytestmark = pytest.mark.integration


class TestSignInAndConnect:
    async def test_sign_in_creates_a_user_a_session_and_a_connected_account(
        self, api: object, fake_oauth: object
    ) -> None:
        await sign_in(api)

        session = await api.get("/api/v1/auth/session")  # type: ignore[attr-defined]
        assert session.status_code == 200
        assert session.json()["user"]["email"] == fake_oauth.email  # type: ignore[attr-defined]

        accounts = (await api.get("/api/v1/accounts")).json()  # type: ignore[attr-defined]
        assert len(accounts) == 1
        assert accounts[0]["email"] == fake_oauth.email  # type: ignore[attr-defined]
        assert accounts[0]["status"] == "active"
        assert accounts[0]["missing_scopes"] == []
        assert accounts[0]["needs_reconnect"] is False

    async def test_the_refresh_expiry_is_known_in_advance(self, api: object) -> None:
        """So the UI can warn before the seven-day expiry, not after (gap A3)."""
        await sign_in(api)
        account = (await api.get("/api/v1/accounts")).json()[0]  # type: ignore[attr-defined]
        assert account["refresh_expires_at"] is not None

    async def test_signing_in_twice_reuses_the_same_account_row(self, api: object) -> None:
        """A weekly re-authorisation must not orphan the mailbox.

        If reconnecting created a new row, the history cursor and everything
        derived from it would be lost every seven days.
        """
        await sign_in(api)
        first = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        await sign_in(api)
        accounts = (await api.get("/api/v1/accounts")).json()  # type: ignore[attr-defined]

        assert len(accounts) == 1
        assert accounts[0]["id"] == first

    async def test_an_unticked_scope_is_surfaced_rather_than_hidden(
        self, app_engine: object, clean_database: None
    ) -> None:
        from httpx import ASGITransport, AsyncClient

        from app.api.v1.auth import oauth_client
        from app.main import app
        from app.modules.providers.oauth.google import GMAIL_READONLY, REQUESTED_SCOPES
        from tests.fakes import FakeOAuthClient

        partial = FakeOAuthClient(
            granted_scopes=tuple(s for s in REQUESTED_SCOPES if s != GMAIL_READONLY)
        )
        app.dependency_overrides[oauth_client] = lambda: partial
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                await sign_in(client)
                account = (await client.get("/api/v1/accounts")).json()[0]

            assert account["status"] == "error"
            assert GMAIL_READONLY in account["missing_scopes"]
            assert "Missing permission" in (account["last_error"] or "")
        finally:
            app.dependency_overrides.pop(oauth_client, None)


class TestReauthAndReconnect:
    async def test_a_dead_refresh_token_moves_the_account_to_reauth_required(
        self, api: object, fake_oauth: object, app_engine: AsyncEngine, owner_engine: AsyncEngine
    ) -> None:
        """Day eight, in Testing mode. The normal case, not an incident."""
        from uuid import UUID

        from app.core.tenancy import tenant_session
        from app.modules.accounts import service
        from app.modules.providers.oauth.base import ReauthRequired

        await sign_in(api)
        user_id = UUID((await api.get("/api/v1/auth/session")).json()["user"]["id"])  # type: ignore[attr-defined]
        account_id = UUID((await api.get("/api/v1/accounts")).json()[0]["id"])  # type: ignore[attr-defined]

        # Age the access token out so a refresh is actually attempted.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE oauth_credentials SET access_expires_at = :moment"),
                {"moment": FROZEN_NOW - timedelta(hours=1)},
            )

        fake_oauth.refresh_fails_with_invalid_grant = True  # type: ignore[attr-defined]

        async with tenant_session(user_id) as session:
            account = await service.get_account(session, account_id)
            with pytest.raises(ReauthRequired):
                await service.ensure_access_token(
                    session,
                    account=account,
                    client=fake_oauth,  # type: ignore[arg-type]
                )

        account_json = (await api.get("/api/v1/accounts")).json()[0]  # type: ignore[attr-defined]
        assert account_json["status"] == "reauth_required"
        assert account_json["needs_reconnect"] is True
        assert account_json["last_error"]

    async def test_a_live_refresh_token_renews_quietly(
        self, api: object, fake_oauth: object, owner_engine: AsyncEngine
    ) -> None:
        from uuid import UUID

        from app.core.tenancy import tenant_session
        from app.modules.accounts import service

        await sign_in(api)
        user_id = UUID((await api.get("/api/v1/auth/session")).json()["user"]["id"])  # type: ignore[attr-defined]
        account_id = UUID((await api.get("/api/v1/accounts")).json()[0]["id"])  # type: ignore[attr-defined]

        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE oauth_credentials SET access_expires_at = :moment"),
                {"moment": FROZEN_NOW - timedelta(hours=1)},
            )

        async with tenant_session(user_id) as session:
            account = await service.get_account(session, account_id)
            token = await service.ensure_access_token(
                session,
                account=account,
                client=fake_oauth,  # type: ignore[arg-type]
            )

        assert token == fake_oauth.access_token  # type: ignore[attr-defined]
        assert fake_oauth.refresh_calls == 1  # type: ignore[attr-defined]
        assert (await api.get("/api/v1/accounts")).json()[0]["status"] == "active"  # type: ignore[attr-defined]

    async def test_a_fresh_access_token_is_not_refreshed(
        self, api: object, fake_oauth: object
    ) -> None:
        from uuid import UUID

        from app.core.tenancy import tenant_session
        from app.modules.accounts import service

        await sign_in(api)
        user_id = UUID((await api.get("/api/v1/auth/session")).json()["user"]["id"])  # type: ignore[attr-defined]
        account_id = UUID((await api.get("/api/v1/accounts")).json()[0]["id"])  # type: ignore[attr-defined]

        async with tenant_session(user_id) as session:
            account = await service.get_account(session, account_id)
            await service.ensure_access_token(
                session,
                account=account,
                client=fake_oauth,  # type: ignore[arg-type]
            )

        assert fake_oauth.refresh_calls == 0  # type: ignore[attr-defined]

    async def test_reconnect_returns_an_authorize_url(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        response = await api.post(  # type: ignore[attr-defined]
            f"/api/v1/accounts/{account_id}/reconnect", headers=csrf_headers(api)
        )
        assert response.status_code == 200
        assert response.json()["authorize_url"].startswith("https://")

    async def test_reconnect_restores_an_account_that_needed_it(
        self, api: object, owner_engine: AsyncEngine
    ) -> None:
        from tests.helpers import authorize_state

        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE connected_accounts SET status = 'reauth_required'"))
        assert (await api.get("/api/v1/accounts")).json()[0]["needs_reconnect"] is True  # type: ignore[attr-defined]

        start = await api.post(  # type: ignore[attr-defined]
            f"/api/v1/accounts/{account_id}/reconnect", headers=csrf_headers(api)
        )
        state = authorize_state(start.json()["authorize_url"])

        callback = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        assert "error=" not in callback.headers["location"]
        assert "reconnected=1" in callback.headers["location"]

        account = (await api.get("/api/v1/accounts")).json()[0]  # type: ignore[attr-defined]
        assert account["status"] == "active"
        assert account["id"] == account_id

    async def test_reconnecting_with_a_different_google_account_is_refused(
        self, api: object, fake_oauth: object
    ) -> None:
        """Otherwise a mailbox silently repoints at somebody else's inbox."""
        from urllib.parse import parse_qs, urlparse

        from tests.helpers import authorize_state

        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        start = await api.post(  # type: ignore[attr-defined]
            f"/api/v1/accounts/{account_id}/reconnect", headers=csrf_headers(api)
        )
        state = authorize_state(start.json()["authorize_url"])

        fake_oauth.email = "someone.else@example.com"  # type: ignore[attr-defined]
        callback = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )

        error = parse_qs(urlparse(callback.headers["location"]).query).get("error", [""])[0]
        assert error == "account_mismatch"


class TestCsrf:
    async def test_reconnect_without_the_header_is_refused(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        response = await api.post(f"/api/v1/accounts/{account_id}/reconnect")  # type: ignore[attr-defined]
        assert response.status_code == 403

    async def test_disconnect_without_the_header_is_refused(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        response = await api.request("DELETE", f"/api/v1/accounts/{account_id}")  # type: ignore[attr-defined]
        assert response.status_code == 403

    async def test_signout_without_the_header_is_refused(self, api: object) -> None:
        await sign_in(api)
        assert (await api.post("/api/v1/auth/signout")).status_code == 403  # type: ignore[attr-defined]

    async def test_a_wrong_header_value_is_refused(self, api: object) -> None:
        await sign_in(api)
        response = await api.post(  # type: ignore[attr-defined]
            "/api/v1/auth/signout", headers={"X-CSRF-Token": "not-the-cookie"}
        )
        assert response.status_code == 403

    async def test_reads_need_no_csrf_token(self, api: object) -> None:
        await sign_in(api)
        assert (await api.get("/api/v1/accounts")).status_code == 200  # type: ignore[attr-defined]


class TestDisconnect:
    async def test_it_revokes_at_google_and_deletes_the_credential(
        self, api: object, fake_oauth: object, owner_engine: AsyncEngine
    ) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        response = await api.request(  # type: ignore[attr-defined]
            "DELETE", f"/api/v1/accounts/{account_id}", headers=csrf_headers(api)
        )
        assert response.status_code == 200
        assert response.json()["status"] == "disconnected"

        assert fake_oauth.revoked == [fake_oauth.refresh_token]  # type: ignore[attr-defined]

        async with owner_engine.connect() as conn:
            remaining = (
                await conn.execute(text("SELECT count(*) FROM oauth_credentials"))
            ).scalar()
        assert remaining == 0, "a decryptable token outlived the disconnect"

    async def test_the_default_retention_is_thirty_days(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        body = (
            await api.request(  # type: ignore[attr-defined]
                "DELETE", f"/api/v1/accounts/{account_id}", headers=csrf_headers(api)
            )
        ).json()
        assert body["purge_after"] is not None

    async def test_purge_now_schedules_an_immediate_purge(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]

        body = (
            await api.request(  # type: ignore[attr-defined]
                "DELETE",
                f"/api/v1/accounts/{account_id}",
                params={"purge": "now"},
                headers=csrf_headers(api),
            )
        ).json()
        assert body["purge_after"] is not None

    async def test_a_disconnected_account_drops_out_of_the_list(self, api: object) -> None:
        await sign_in(api)
        account_id = (await api.get("/api/v1/accounts")).json()[0]["id"]  # type: ignore[attr-defined]
        await api.request(  # type: ignore[attr-defined]
            "DELETE", f"/api/v1/accounts/{account_id}", headers=csrf_headers(api)
        )

        assert (await api.get("/api/v1/accounts")).json() == []  # type: ignore[attr-defined]
        with_history = (
            await api.get("/api/v1/accounts", params={"include_disconnected": True})  # type: ignore[attr-defined]
        ).json()
        assert len(with_history) == 1


class TestSignOut:
    async def test_the_session_stops_working(self, api: object) -> None:
        await sign_in(api)
        assert (await api.get("/api/v1/auth/session")).status_code == 200  # type: ignore[attr-defined]

        response = await api.post("/api/v1/auth/signout", headers=csrf_headers(api))  # type: ignore[attr-defined]
        assert response.status_code == 204

        assert (await api.get("/api/v1/auth/session")).status_code == 401  # type: ignore[attr-defined]

    async def test_a_revoked_session_cookie_cannot_be_reused(self, api: object) -> None:
        """Clearing the cookie is not the mechanism; revoking the row is."""
        await sign_in(api)
        stolen = api.cookies.get("maail_session")  # type: ignore[attr-defined]
        csrf = api.cookies.get("maail_csrf")  # type: ignore[attr-defined]

        await api.post("/api/v1/auth/signout", headers=csrf_headers(api))  # type: ignore[attr-defined]

        api.cookies.set("maail_session", stolen)  # type: ignore[attr-defined]
        api.cookies.set("maail_csrf", csrf)  # type: ignore[attr-defined]
        assert (await api.get("/api/v1/auth/session")).status_code == 401  # type: ignore[attr-defined]
