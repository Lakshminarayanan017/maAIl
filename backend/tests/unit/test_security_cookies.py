"""Session tokens, CSRF double-submit, and the signed OAuth flow cookie."""

from __future__ import annotations

import base64
import json

from fastapi import Request, Response

from app.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    OAUTH_COOKIE,
    SESSION_COOKIE,
    OAuthFlow,
    csrf_token_valid,
    hash_token,
    issue_session_token,
    new_csrf_token,
    read_oauth_cookie,
    set_oauth_cookie,
    set_session_cookies,
)


def make_request(cookies: dict[str, str] | None = None, headers: dict[str, str] | None = None):
    raw_headers = []
    if cookies:
        jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", jar.encode()))
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    return Request({"type": "http", "method": "POST", "headers": raw_headers, "path": "/"})


class TestSessionTokens:
    def test_the_token_is_never_what_gets_stored(self) -> None:
        token, stored = issue_session_token()
        assert stored == hash_token(token)
        assert token.encode() not in stored
        assert len(stored) == 32

    def test_two_tokens_differ(self) -> None:
        assert issue_session_token()[0] != issue_session_token()[0]

    def test_the_session_cookie_is_httponly_and_the_csrf_cookie_is_not(self) -> None:
        response = Response()
        set_session_cookies(response, "session-token", "csrf-token")
        headers = [v for k, v in response.raw_headers if k == b"set-cookie"]
        session_header = next(h.decode() for h in headers if h.startswith(SESSION_COOKIE.encode()))
        csrf_header = next(h.decode() for h in headers if h.startswith(CSRF_COOKIE.encode()))

        assert "HttpOnly" in session_header
        assert "SameSite=lax" in session_header.replace("samesite", "SameSite")
        # Readable on purpose: the app has to echo it back in a header.
        assert "HttpOnly" not in csrf_header


class TestCsrf:
    def test_matching_cookie_and_header_pass(self) -> None:
        token = new_csrf_token()
        request = make_request({CSRF_COOKIE: token}, {CSRF_HEADER: token})
        assert csrf_token_valid(request) is True

    def test_a_missing_header_fails(self) -> None:
        assert csrf_token_valid(make_request({CSRF_COOKIE: new_csrf_token()})) is False

    def test_a_missing_cookie_fails(self) -> None:
        assert csrf_token_valid(make_request(headers={CSRF_HEADER: new_csrf_token()})) is False

    def test_a_mismatch_fails(self) -> None:
        request = make_request({CSRF_COOKIE: new_csrf_token()}, {CSRF_HEADER: new_csrf_token()})
        assert csrf_token_valid(request) is False

    def test_an_empty_pair_does_not_count_as_a_match(self) -> None:
        """Two empty strings are equal. They are not an authorisation."""
        request = make_request({CSRF_COOKIE: ""}, {CSRF_HEADER: ""})
        assert csrf_token_valid(request) is False


class TestOAuthFlowCookie:
    def test_round_trip(self) -> None:
        flow = OAuthFlow(state="state-value", code_verifier="verifier-value", purpose="signin")
        response = Response()
        set_oauth_cookie(response, flow)
        value = _cookie_value(response, OAUTH_COOKIE)

        recovered = read_oauth_cookie(make_request({OAUTH_COOKIE: value}))
        assert recovered == flow

    def test_it_carries_the_account_for_a_reconnect(self) -> None:
        flow = OAuthFlow(state="s", code_verifier="v", purpose="reconnect", account_id="acc-1")
        response = Response()
        set_oauth_cookie(response, flow)
        recovered = read_oauth_cookie(
            make_request({OAUTH_COOKIE: _cookie_value(response, OAUTH_COOKIE)})
        )
        assert recovered is not None
        assert recovered.account_id == "acc-1"
        assert recovered.purpose == "reconnect"

    def test_the_verifier_never_reaches_the_database(self) -> None:
        """It lives in the cookie, signed, and nowhere else.

        A PKCE verifier in a table is a secret at rest with no reason to be
        there; the ledger only ever sees a hash of the state.
        """
        response = Response()
        set_oauth_cookie(
            response, OAuthFlow(state="s", code_verifier="secret-verifier", purpose="signin")
        )
        header = next(h.decode() for k, h in response.raw_headers if k == b"set-cookie")
        assert "HttpOnly" in header

    def test_a_tampered_payload_is_rejected(self) -> None:
        response = Response()
        set_oauth_cookie(response, OAuthFlow(state="original", code_verifier="v", purpose="signin"))
        value = _cookie_value(response, OAUTH_COOKIE)
        payload, signature = value.split(".", 1)

        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        decoded["state"] = "attacker-chosen"
        forged = (
            base64.urlsafe_b64encode(json.dumps(decoded, separators=(",", ":")).encode())
            .decode()
            .rstrip("=")
        )

        assert read_oauth_cookie(make_request({OAUTH_COOKIE: f"{forged}.{signature}"})) is None

    def test_nonsense_is_rejected_rather_than_raised(self) -> None:
        for value in ("", "not-a-cookie", "a.b.c", "!!!.???", "."):
            assert read_oauth_cookie(make_request({OAUTH_COOKIE: value})) is None

    def test_an_unknown_purpose_is_rejected(self) -> None:
        from app.core.security import _b64, _sign

        payload = json.dumps(
            {"state": "s", "verifier": "v", "purpose": "exfiltrate", "account_id": None},
            separators=(",", ":"),
        ).encode()
        value = f"{_b64(payload)}.{_b64(_sign(payload))}"
        assert read_oauth_cookie(make_request({OAUTH_COOKIE: value})) is None

    def test_no_cookie_means_no_flow(self) -> None:
        assert read_oauth_cookie(make_request()) is None


def _cookie_value(response: Response, name: str) -> str:
    header = next(
        h.decode()
        for k, h in response.raw_headers
        if k == b"set-cookie" and h.startswith(name.encode())
    )
    return header.split("=", 1)[1].split(";", 1)[0]
