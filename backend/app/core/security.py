"""Sessions, CSRF, and the signed cookie that carries an OAuth flow.

Three cookies, each with one job:

``maail_session``  httpOnly, SameSite=Lax. A random 256-bit token. Only its
                   sha256 is stored, so a database dump is not a set of
                   working sessions.
``maail_csrf``     readable by JavaScript on purpose: the double-submit half.
                   SameSite=Lax already blocks most cross-site writes; this
                   covers the rest, including a same-site subdomain.
``maail_oauth``    httpOnly, short lived, signed. Holds the OAuth state, the
                   PKCE verifier and what the flow is for. Signed rather than
                   stored, so a verifier never reaches the database; bound to
                   the browser, so a stolen authorization code cannot be
                   redeemed from somewhere else.

Everything compares with ``hmac.compare_digest``. A token check that returns
early on the first wrong byte is a token check with a timing side channel.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import Request, Response

from app.core.config import settings

SESSION_COOKIE = "maail_session"
CSRF_COOKIE = "maail_csrf"
OAUTH_COOKIE = "maail_oauth"
CSRF_HEADER = "X-CSRF-Token"

#: An authorization round trip is a few seconds of human attention, not a day.
OAUTH_FLOW_TTL_SECONDS = 15 * 60

OAuthPurpose = Literal["signin", "reconnect"]

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "OAUTH_COOKIE",
    "SESSION_COOKIE",
    "OAuthFlow",
    "clear_oauth_cookie",
    "clear_session_cookies",
    "csrf_token_valid",
    "hash_token",
    "issue_session_token",
    "new_csrf_token",
    "read_oauth_cookie",
    "set_oauth_cookie",
    "set_session_cookies",
]


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------
def issue_session_token() -> tuple[str, bytes]:
    """A new session token and the hash to store. The token is never stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_valid(request: Request) -> bool:
    """Double submit: the header must equal the cookie, and both must exist."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header:
        return False
    return hmac.compare_digest(cookie, header)


# ---------------------------------------------------------------------------
# cookies
# ---------------------------------------------------------------------------
def _base_cookie_kwargs() -> dict[str, Any]:
    return {
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }


def set_session_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    max_age = settings.session_ttl_days * 24 * 60 * 60
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, max_age=max_age, **_base_cookie_kwargs()
    )
    # Not httpOnly: the browser app has to read it to echo it back in a header.
    # That is the mechanism, not an oversight.
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, max_age=max_age, **_base_cookie_kwargs()
    )


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", samesite="lax", secure=settings.cookie_secure)


# ---------------------------------------------------------------------------
# the OAuth flow cookie
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OAuthFlow:
    state: str
    code_verifier: str
    purpose: OAuthPurpose
    #: Set only for a reconnect. Re-checked against the session at callback,
    #: because a signed value proves it was not tampered with, not that the
    #: person presenting it still owns the account.
    account_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "verifier": self.code_verifier,
            "purpose": self.purpose,
            "account_id": self.account_id,
        }


def _sign(payload: bytes) -> bytes:
    return hmac.new(
        settings.session_secret.get_secret_value().encode("utf-8"), payload, hashlib.sha256
    ).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def set_oauth_cookie(response: Response, flow: OAuthFlow) -> None:
    payload = json.dumps(flow.to_payload(), separators=(",", ":")).encode("utf-8")
    value = f"{_b64(payload)}.{_b64(_sign(payload))}"
    response.set_cookie(
        OAUTH_COOKIE,
        value,
        httponly=True,
        max_age=OAUTH_FLOW_TTL_SECONDS,
        **_base_cookie_kwargs(),
    )


def read_oauth_cookie(request: Request) -> OAuthFlow | None:
    """Return the flow this browser started, or None if it cannot be trusted."""
    raw = request.cookies.get(OAUTH_COOKIE)
    if not raw or raw.count(".") != 1:
        return None

    encoded_payload, encoded_signature = raw.split(".", 1)
    try:
        payload = _unb64(encoded_payload)
        signature = _unb64(encoded_signature)
    except Exception:
        return None

    if not hmac.compare_digest(signature, _sign(payload)):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    state = data.get("state")
    verifier = data.get("verifier")
    purpose = data.get("purpose")
    if not isinstance(state, str) or not isinstance(verifier, str):
        return None
    if purpose not in ("signin", "reconnect"):
        return None

    account_id = data.get("account_id")
    if account_id is not None and not isinstance(account_id, str):
        return None

    return OAuthFlow(state=state, code_verifier=verifier, purpose=purpose, account_id=account_id)


def clear_oauth_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_COOKIE, path="/", samesite="lax", secure=settings.cookie_secure)
