"""Sign in with Google, and the session endpoints.

Zero-LLM zone. Nothing in this file or anything it imports may reach a model.

The callback is the security-critical handler, so its checks run in a fixed
order and each one has a reason:

1. a signed flow cookie must exist          -- this browser started this flow
2. the ``state`` parameter must match it    -- the redirect was not forged
3. the state must be unspent in the ledger  -- the redirect is not a replay
4. only then is the code exchanged          -- nothing before this costs a call

An attacker who can make the browser follow a crafted callback URL gets past
none of 1, 2 or 3, because all three are bound to a secret the browser holds
and the ledger has seen exactly once.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import AuthContext, UnscopedSession, require_csrf
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    SESSION_COOKIE,
    OAuthFlow,
    clear_oauth_cookie,
    clear_session_cookies,
    hash_token,
    issue_session_token,
    new_csrf_token,
    read_oauth_cookie,
    set_oauth_cookie,
    set_session_cookies,
)
from app.core.tenancy import set_tenant
from app.database.engine import SessionFactory
from app.modules.accounts import service, states
from app.modules.providers.oauth.base import (
    OAuthError,
    ReauthRequired,
    TokenGrant,
    UserIdentity,
)
from app.modules.providers.oauth.google import GoogleOAuthClient

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)

# make_interval rather than ':ttl::interval': SQLAlchemy's text() reads the
# '::' cast as the start of another bind parameter and leaves the colon in.
_CREATE_SESSION = text(
    "SELECT app_create_session(:user_id, :token_hash, :user_agent, "
    "make_interval(days => :ttl_days))"
)
_REVOKE_SESSION = text("SELECT app_revoke_session(:token_hash)")


class StartResponse(BaseModel):
    authorize_url: str


class SessionUser(BaseModel):
    id: str
    email: str
    name: str | None
    timezone: str


class SessionResponse(BaseModel):
    authenticated: Literal[True]
    user: SessionUser


def oauth_client() -> GoogleOAuthClient:
    return GoogleOAuthClient()


OAuth = Annotated[GoogleOAuthClient, Depends(oauth_client)]


def _redirect_to_app(path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(
        f"{settings.web_base_url.rstrip('/')}{path}{query}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _failed(reason: str, *, detail: str | None = None) -> RedirectResponse:
    """Send the browser back with a reason code, never with provider text.

    A provider error body can echo the authorization code or the client
    secret. The code goes in the URL; the detail goes in the log.
    """
    log.warning("auth.callback_failed", reason=reason, detail=detail)
    response = _redirect_to_app("/onboarding/connect", error=reason)
    clear_oauth_cookie(response)
    return response


# ---------------------------------------------------------------------------
# starting a flow
# ---------------------------------------------------------------------------
@router.post(
    "/google/start",
    response_model=StartResponse,
    summary="Begin Google sign-in and Gmail connection",
)
async def start_google(
    response: Response, session: UnscopedSession, client: OAuth
) -> StartResponse:
    """No CSRF token here, because there is no session yet to protect.

    Login CSRF is handled instead by binding the flow to this browser: the
    callback only accepts a state that matches the cookie set below.
    """
    try:
        request_ = client.build_authorization_request(prompt_consent=True)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    async with session.begin():
        await states.prune(session)
        await states.record(session, state=request_.state, purpose="signin")

    set_oauth_cookie(
        response,
        OAuthFlow(state=request_.state, code_verifier=request_.code_verifier, purpose="signin"),
    )
    return StartResponse(authorize_url=request_.authorize_url)


# ---------------------------------------------------------------------------
# the callback
# ---------------------------------------------------------------------------
@router.get("/google/callback", summary="Google redirects the browser here")
async def google_callback(
    request: Request,
    client: OAuth,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> RedirectResponse:
    if error:
        # "access_denied" means the person said no. That is an outcome, not a
        # fault, and the screen says so.
        return _failed("access_denied" if error == "access_denied" else "provider_error")

    flow = read_oauth_cookie(request)
    if flow is None:
        return _failed("flow_missing")
    if not code or not state:
        return _failed("malformed_callback")
    if not hmac.compare_digest(state, flow.state):
        return _failed("state_mismatch")

    async with SessionFactory() as db:
        async with db.begin():
            consumed = await states.consume(db, state=state)
    if consumed is None:
        return _failed("state_expired_or_replayed")
    if consumed.purpose != flow.purpose:
        return _failed("state_purpose_mismatch")

    try:
        grant = await client.exchange_code(code=code, code_verifier=flow.code_verifier)
        identity = await client.fetch_identity(access_token=grant.access_token)
    except ReauthRequired as exc:
        return _failed("grant_rejected", detail=str(exc))
    except OAuthError as exc:
        return _failed("exchange_failed", detail=str(exc))

    if flow.purpose == "reconnect":
        return await _finish_reconnect(request, flow, grant, identity)
    return await _finish_signin(request, grant, identity)


async def _finish_signin(
    request: Request, grant: TokenGrant, identity: UserIdentity
) -> RedirectResponse:
    async with SessionFactory() as db:
        async with db.begin():
            user_id = await service.upsert_user(db, email=identity.email, name=identity.name)

    async with SessionFactory() as db:
        async with db.begin():
            await set_tenant(db, user_id)
            await service.attach_grant(
                db,
                user_id=user_id,
                provider="gmail",
                email=identity.email,
                grant=grant,
            )

    token, token_hash = issue_session_token()
    async with SessionFactory() as db:
        async with db.begin():
            await db.execute(
                _CREATE_SESSION,
                {
                    "user_id": str(user_id),
                    "token_hash": token_hash,
                    "user_agent": request.headers.get("user-agent"),
                    "ttl_days": settings.session_ttl_days,
                },
            )

    response = _redirect_to_app("/onboarding/connect", connected="1")
    set_session_cookies(response, token, new_csrf_token())
    clear_oauth_cookie(response)
    log.info("auth.signed_in", user_id=str(user_id))
    return response


async def _finish_reconnect(
    request: Request, flow: OAuthFlow, grant: TokenGrant, identity: UserIdentity
) -> RedirectResponse:
    """A reconnect must prove ownership, not just possession of a signed cookie.

    The cookie says which account the flow was started for and cannot be
    tampered with. It does not say the browser presenting it is still signed
    in as that account's owner, so the session is re-checked here and the
    account is loaded under RLS.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return _failed("reconnect_requires_session")

    async with SessionFactory() as db:
        async with db.begin():
            resolved = (
                await db.execute(
                    text("SELECT app_resolve_session(:token_hash)"),
                    {"token_hash": hash_token(token)},
                )
            ).scalar()
            if resolved is None:
                return _failed("reconnect_requires_session")
            user_id = UUID(str(resolved))
            await set_tenant(db, user_id)

            if flow.account_id:
                try:
                    account = await service.get_account(db, UUID(flow.account_id))
                except (service.AccountNotFound, ValueError):
                    return _failed("account_not_found")
                if account.provider_account_email.lower() != identity.email.lower():
                    # Reconnecting with a different Google account would
                    # silently repoint a mailbox. It is a new connection, not
                    # a reconnection, and the user should say so explicitly.
                    return _failed("account_mismatch")

            await service.attach_grant(
                db,
                user_id=user_id,
                provider="gmail",
                email=identity.email,
                grant=grant,
            )

    response = _redirect_to_app("/settings", reconnected="1")
    clear_oauth_cookie(response)
    log.info("auth.reconnected", user_id=str(user_id))
    return response


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------
@router.get("/session", response_model=SessionResponse, summary="Who is signed in")
async def read_session(auth: AuthContext) -> SessionResponse:
    row = (
        (
            await auth.session.execute(
                text("SELECT id, email, name, timezone FROM users WHERE id = :id"),
                {"id": str(auth.user_id)},
            )
        )
        .mappings()
        .one()
    )
    return SessionResponse(
        authenticated=True,
        user=SessionUser(
            id=str(row["id"]),
            email=row["email"],
            name=row["name"],
            timezone=row["timezone"],
        ),
    )


@router.post(
    "/signout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
    summary="End this session",
)
async def signout(request: Request, response: Response, session: UnscopedSession) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        async with session.begin():
            await session.execute(_REVOKE_SESSION, {"token_hash": hash_token(token)})
    clear_session_cookies(response)
