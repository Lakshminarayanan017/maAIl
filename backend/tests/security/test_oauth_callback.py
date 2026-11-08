"""Phase 1 blocking gate: an invalid OAuth state is rejected.

> Blocking gates. Invalid OAuth state rejected. No plaintext token in the
> database or logs. Cross-tenant account access rejected. Zero LLM calls in
> the auth path.
> (09-execution-plan.md, phase 1)

Each test below is one way the callback can be attacked, and the order
matters: a state check that happens after the code exchange has already paid
for the attack.
"""

from __future__ import annotations

import pytest

from tests.helpers import authorize_state

pytestmark = [pytest.mark.security, pytest.mark.integration]


async def start_flow(api: object) -> tuple[str, str]:
    response = await api.post("/api/v1/auth/google/start")  # type: ignore[attr-defined]
    assert response.status_code == 200
    return authorize_state(response.json()["authorize_url"]), response.text


def error_of(response: object) -> str:
    from urllib.parse import parse_qs, urlparse

    location = response.headers["location"]  # type: ignore[attr-defined]
    return parse_qs(urlparse(location).query).get("error", [""])[0]


class TestStateIsEnforced:
    async def test_a_state_the_server_never_issued_is_rejected(self, api: object) -> None:
        await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback",
            params={"code": "c", "state": "a-state-nobody-issued"},
        )
        assert response.status_code == 303
        assert error_of(response) == "state_mismatch"

    async def test_a_valid_state_cannot_be_replayed(self, api: object) -> None:
        """Single use, enforced in the ledger rather than in the cookie.

        The flow cookie is captured and put back before the replay, because
        otherwise the first callback clears it and the request is turned away
        by the cookie check -- which proves the cookie works, not the ledger.
        This models someone who kept a copy of both.
        """
        state, _ = await start_flow(api)
        stolen_cookie = api.cookies.get("maail_oauth")  # type: ignore[attr-defined]
        assert stolen_cookie

        first = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        assert error_of(first) == ""

        api.cookies.set("maail_oauth", stolen_cookie)  # type: ignore[attr-defined]
        second = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        assert error_of(second) == "state_expired_or_replayed"

    async def test_a_callback_with_no_flow_cookie_is_rejected(self, api: object) -> None:
        """The redirect has to arrive at the browser that started the flow."""
        state, _ = await start_flow(api)
        api.cookies.delete("maail_oauth")  # type: ignore[attr-defined]

        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        assert error_of(response) == "flow_missing"

    async def test_a_forged_flow_cookie_is_rejected(self, api: object) -> None:
        """A cookie with a bad signature is no cookie at all.

        Deleted before it is replaced: httpx keeps the server-set cookie
        alongside a same-named one added by the client, and sends the
        server's, so a plain `set` would quietly test nothing.
        """
        state, _ = await start_flow(api)
        api.cookies.delete("maail_oauth")  # type: ignore[attr-defined]
        api.cookies.set("maail_oauth", "forged.signature")  # type: ignore[attr-defined]

        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        assert error_of(response) == "flow_missing"

    async def test_a_callback_without_a_code_is_rejected(self, api: object) -> None:
        state, _ = await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"state": state}
        )
        assert error_of(response) == "malformed_callback"

    async def test_the_code_is_never_exchanged_when_the_state_is_wrong(
        self, api: object, fake_oauth: object
    ) -> None:
        """Order of checks, asserted.

        A state check that runs after the exchange still rejects the request,
        but it has already spent a network call and, with a real provider,
        burned the authorization code.
        """
        await start_flow(api)
        before = len(fake_oauth.issued)  # type: ignore[attr-defined]

        await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": "wrong"}
        )

        assert fake_oauth.refresh_calls == 0  # type: ignore[attr-defined]
        assert len(fake_oauth.issued) == before  # type: ignore[attr-defined]


class TestProviderErrors:
    async def test_declining_consent_is_reported_as_a_choice(self, api: object) -> None:
        await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"error": "access_denied"}
        )
        assert error_of(response) == "access_denied"

    async def test_other_provider_errors_are_not_echoed_back(self, api: object) -> None:
        """A provider error body can contain the code or the client secret.

        The browser gets a reason code; the detail goes to the log.
        """
        await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback",
            params={"error": "server_error&secret=leak"},
        )
        assert error_of(response) == "provider_error"
        assert "leak" not in response.headers["location"]  # type: ignore[attr-defined]


class TestSessionIssuance:
    async def test_a_successful_callback_sets_both_cookies(self, api: object) -> None:
        state, _ = await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )

        assert error_of(response) == "", response.headers["location"]

        cookies = response.headers.get_list("set-cookie")  # type: ignore[attr-defined]
        session_cookies = [c for c in cookies if c.startswith("maail_session=")]
        csrf_cookies = [c for c in cookies if c.startswith("maail_csrf=")]

        assert session_cookies, f"no session cookie was set; got {cookies}"
        assert csrf_cookies, f"no csrf cookie was set; got {cookies}"
        assert "HttpOnly" in session_cookies[0]
        assert "HttpOnly" not in csrf_cookies[0]

    async def test_the_flow_cookie_is_cleared_afterwards(self, api: object) -> None:
        state, _ = await start_flow(api)
        response = await api.get(  # type: ignore[attr-defined]
            "/api/v1/auth/google/callback", params={"code": "c", "state": state}
        )
        cleared = [
            c
            for c in response.headers.get_list("set-cookie")  # type: ignore[attr-defined]
            if c.startswith("maail_oauth=")
        ]
        assert cleared, "the one-shot flow cookie should not survive the callback"
