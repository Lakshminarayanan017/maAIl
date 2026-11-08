"""Google OAuth 2.0, with PKCE, requesting ``gmail.readonly`` and nothing else.

Deliberate choices:

- **PKCE on a confidential client.** The secret alone would do, but PKCE costs
  one hash and removes authorization-code interception from the threat model.
- **``prompt=consent``** on first connect and on reconnect. Without it Google
  returns no refresh token when a grant already exists, and the failure is
  silent until the first access token expires an hour later.
- **``include_granted_scopes`` off.** Incremental authorization would quietly
  widen the grant. Sending mail gets its own, separate authorisation later;
  that is a product promise on screen 02, so it is enforced here.
- **Scopes are verified against what Google granted**, not against what was
  asked for. A user can untick a scope on the consent screen, and an account
  that is missing ``gmail.readonly`` must say so rather than fail at sync.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from app.core.clock import get_clock
from app.core.config import settings
from app.core.logging import get_logger
from app.modules.providers.oauth.base import (
    AuthorizationRequest,
    OAuthError,
    ReauthRequired,
    TokenGrant,
    UserIdentity,
)
from app.modules.providers.oauth.pkce import new_state, new_verifier, verifier_challenge

log = get_logger(__name__)

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
USERINFO_EMAIL = "https://www.googleapis.com/auth/userinfo.email"

#: Everything v1 asks for. Sending is not here, and will not be added to it.
REQUESTED_SCOPES: tuple[str, ...] = ("openid", USERINFO_EMAIL, GMAIL_READONLY)

#: What an account must actually hold to be usable. Google normalises the
#: OpenID scopes, so only the ones that carry capability are required.
REQUIRED_SCOPES: frozenset[str] = frozenset({GMAIL_READONLY, USERINFO_EMAIL})

#: Google answers with these when the grant is gone rather than malformed.
_REAUTH_CODES = frozenset({"invalid_grant", "unauthorized_client"})

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class GoogleOAuthClient:
    """Read-only Gmail access. Holds no tool that acts."""

    def __init__(self, *, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    @property
    def required_scopes(self) -> frozenset[str]:
        return REQUIRED_SCOPES

    # -- authorization ----------------------------------------------------
    def build_authorization_request(
        self, *, prompt_consent: bool = True, login_hint: str | None = None
    ) -> AuthorizationRequest:
        if not settings.google_oauth_configured:
            raise OAuthError(
                "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET, then restart the API."
            )

        state = new_state()
        verifier = new_verifier()

        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUESTED_SCOPES),
            "state": state,
            "code_challenge": verifier_challenge(verifier),
            "code_challenge_method": "S256",
            # Without offline there is no refresh token, and the connection
            # dies an hour later with no way to renew it.
            "access_type": "offline",
            # Off on purpose: incremental authorization would silently widen
            # the grant beyond what screen 02 told the user it was asking for.
            "include_granted_scopes": "false",
        }
        if prompt_consent:
            params["prompt"] = "consent"
        if login_hint:
            params["login_hint"] = login_hint

        return AuthorizationRequest(
            authorize_url=f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}",
            state=state,
            code_verifier=verifier,
        )

    # -- token exchange ---------------------------------------------------
    async def exchange_code(self, *, code: str, code_verifier: str) -> TokenGrant:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "code_verifier": code_verifier,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
        }
        data = await self._post(TOKEN_ENDPOINT, payload)

        refresh_token = data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            # Google withholds it when a grant already exists and consent was
            # not re-prompted. Failing here beats discovering it in an hour.
            raise OAuthError(
                "Google returned no refresh token. Remove Maail from your Google "
                "account permissions and connect again.",
                code="no_refresh_token",
            )
        return self._grant(data, refresh_token=refresh_token, fresh_refresh=True)

    async def refresh(self, *, refresh_token: str) -> TokenGrant:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
        }
        data = await self._post(TOKEN_ENDPOINT, payload)
        # A refresh normally returns no new refresh token; the old one stands
        # and its expiry is unchanged, so fresh_refresh is False.
        rotated = data.get("refresh_token")
        return self._grant(
            data,
            refresh_token=rotated if isinstance(rotated, str) and rotated else refresh_token,
            fresh_refresh=False,
        )

    # -- identity and revocation -----------------------------------------
    async def fetch_identity(self, *, access_token: str) -> UserIdentity:
        async with self._client() as client:
            response = await client.get(
                USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
            )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ReauthRequired("Google rejected the access token", code="invalid_token")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise OAuthError(f"Google userinfo failed with {response.status_code}")

        data = response.json()
        email = data.get("email")
        if not email:
            raise OAuthError("Google returned no email address for this account")
        if data.get("email_verified") is False:
            raise OAuthError("That Google account has an unverified email address")

        return UserIdentity(email=email, name=data.get("name"), provider_subject=data.get("sub"))

    async def revoke(self, *, token: str) -> bool:
        """Best effort. A disconnect must not fail because Google is down.

        Gap A4: Google keeps at most a hundred live refresh tokens per account
        per client and silently drops the oldest, so revoking on disconnect is
        hygiene rather than politeness.
        """
        try:
            async with self._client() as client:
                response = await client.post(REVOKE_ENDPOINT, data={"token": token})
        except httpx.HTTPError as exc:
            log.warning("oauth.revoke_unreachable", error=str(exc))
            return False
        if response.status_code >= httpx.codes.BAD_REQUEST:
            log.warning("oauth.revoke_refused", status=response.status_code)
            return False
        return True

    # -- plumbing ---------------------------------------------------------
    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return _Borrowed(self._http)  # type: ignore[return-value]
        return httpx.AsyncClient(timeout=_TIMEOUT)

    async def _post(self, url: str, payload: dict[str, str]) -> dict[str, object]:
        try:
            async with self._client() as client:
                response = await client.post(url, data=payload)
        except httpx.HTTPError as exc:
            raise OAuthError(f"Could not reach Google: {exc}") from exc

        if response.status_code >= httpx.codes.BAD_REQUEST:
            body = _safe_json(response)
            code = str(body.get("error", "")) or None
            # The response body can echo the code or the client secret back.
            # Log the code only.
            log.warning("oauth.token_endpoint_error", status=response.status_code, code=code)
            if code in _REAUTH_CODES:
                raise ReauthRequired(
                    "Google will not renew this connection. Reconnect the account.", code=code
                )
            raise OAuthError(f"Google refused the token request ({code or response.status_code})")

        return _safe_json(response)

    def _grant(
        self, data: dict[str, object], *, refresh_token: str, fresh_refresh: bool
    ) -> TokenGrant:
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("Google returned no access token")

        now = get_clock().now()
        expires_in = data.get("expires_in")
        lifetime = int(expires_in) if isinstance(expires_in, (int, float, str)) else 3600

        raw_scope = data.get("scope")
        scope_text = raw_scope if isinstance(raw_scope, str) else ""

        refresh_expires_at = None
        if fresh_refresh and settings.google_oauth_testing_mode:
            refresh_expires_at = now + timedelta(days=settings.google_testing_refresh_ttl_days)

        return TokenGrant(
            access_token=access_token,
            refresh_token=refresh_token,
            granted_scopes=tuple(sorted(scope_text.split())) if scope_text else (),
            access_expires_at=now + timedelta(seconds=lifetime),
            refresh_expires_at=refresh_expires_at,
            raw_scope=scope_text,
        )


def missing_scopes(granted: object) -> tuple[str, ...]:
    """Which required scopes the user did not grant.

    A consent screen lets someone untick a box. An account missing
    ``gmail.readonly`` must say so on the settings card, not fail at the first
    sync with a 403 nobody can interpret.
    """
    if isinstance(granted, str):
        held = set(granted.split())
    elif isinstance(granted, Iterable):
        held = {str(scope) for scope in granted}
    else:
        held = set()
    return tuple(sorted(REQUIRED_SCOPES - held))


def _safe_json(response: httpx.Response) -> dict[str, object]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class _Borrowed:
    """Lets an injected client be used with ``async with`` without closing it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_: object) -> None:
        return None
