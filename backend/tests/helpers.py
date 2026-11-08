"""Small helpers shared by the phase 1 API tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def authorize_state(authorize_url: str) -> str:
    """Pull the state out of the URL the client was told to send the user to."""
    return parse_qs(urlparse(authorize_url).query)["state"][0]


async def sign_in(client: object, *, code: str = "fake-auth-code") -> str:
    """Run a complete sign-in and return the state that was used.

    Leaves the client holding a session cookie and a CSRF cookie, exactly as
    a browser would after the redirect.
    """
    start = await client.post("/api/v1/auth/google/start")  # type: ignore[attr-defined]
    assert start.status_code == 200, start.text
    state = authorize_state(start.json()["authorize_url"])

    callback = await client.get(  # type: ignore[attr-defined]
        "/api/v1/auth/google/callback", params={"code": code, "state": state}
    )
    assert callback.status_code == 303, callback.text
    assert "error=" not in callback.headers["location"], callback.headers["location"]
    return state


def csrf_headers(client: object) -> dict[str, str]:
    """The double-submit header a browser would send."""
    token = client.cookies.get("maail_csrf")  # type: ignore[attr-defined]
    return {"X-CSRF-Token": token} if token else {}
