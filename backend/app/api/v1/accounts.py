"""Connected accounts: list, reconnect, disconnect.

Zero-LLM zone.

Every handler reads through ``AuthContext``, so RLS is armed before the first
query and none of these functions writes ``WHERE user_id = ...`` by hand.
Another tenant's account id returns 404, the same answer as an id that was
never issued -- an endpoint that distinguishes the two is an endpoint that
confirms which ids exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AuthContext, require_csrf
from app.api.v1.auth import OAuth
from app.core.logging import get_logger
from app.core.security import OAuthFlow, set_oauth_cookie
from app.modules.accounts import service, states
from app.modules.accounts.service import AccountNotFound, AccountView
from app.modules.providers.oauth.base import OAuthError

router = APIRouter(prefix="/accounts", tags=["accounts"])
log = get_logger(__name__)


class SyncProgress(BaseModel):
    total: int | None = None
    done: int = 0
    last_synced_at: datetime | None = None


class AccountOut(BaseModel):
    id: UUID
    email: str
    provider: str
    status: str
    granted_scopes: list[str]
    #: Non-empty when the person unticked something on the consent screen.
    #: The settings card names what is missing rather than failing at sync.
    missing_scopes: list[str]
    #: Returned so the client can warn *before* the seven-day Testing-mode
    #: expiry bites, rather than after a sync fails (gap A3).
    refresh_expires_at: datetime | None
    needs_reconnect: bool
    expires_soon: bool
    connected_at: datetime
    last_error: str | None
    sync_progress: SyncProgress
    disconnected_at: datetime | None
    purge_after: datetime | None


class ReconnectResponse(BaseModel):
    authorize_url: str


class DisconnectResponse(BaseModel):
    id: UUID
    status: str
    purge_after: datetime | None = Field(
        description="When the mail for this account is deleted. Credentials go immediately."
    )


def _to_out(view: AccountView) -> AccountOut:
    return AccountOut(
        id=view.id,
        email=view.email,
        provider=view.provider,
        status=view.status.value,
        granted_scopes=list(view.granted_scopes),
        missing_scopes=list(view.missing_scopes),
        refresh_expires_at=view.refresh_expires_at,
        needs_reconnect=view.needs_reconnect,
        expires_soon=view.expires_soon,
        connected_at=view.connected_at,
        last_error=view.last_error,
        sync_progress=SyncProgress(
            total=view.initial_sync_total,
            done=view.initial_sync_done,
            last_synced_at=view.last_delta_sync_at,
        ),
        disconnected_at=view.disconnected_at,
        purge_after=view.purge_after,
    )


@router.get("", response_model=list[AccountOut], summary="Accounts connected to this user")
async def list_accounts(
    auth: AuthContext,
    include_disconnected: Annotated[bool, Query()] = False,
) -> list[AccountOut]:
    views = await service.list_accounts(auth.session, include_disconnected=include_disconnected)
    return [_to_out(view) for view in views]


@router.post(
    "/{account_id}/reconnect",
    response_model=ReconnectResponse,
    dependencies=[Depends(require_csrf)],
    summary="Start re-authorisation for an account",
)
async def reconnect(
    account_id: UUID, auth: AuthContext, response: Response, client: OAuth
) -> ReconnectResponse:
    """The weekly path, not an error path (gap A3).

    ``login_hint`` is the account's own address, so the consent screen does
    not invite the user to pick a different Google account and silently
    repoint their mailbox. The callback re-checks the address anyway.
    """
    try:
        account = await service.get_account(auth.session, account_id)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account") from exc

    try:
        request_ = client.build_authorization_request(
            prompt_consent=True, login_hint=account.provider_account_email
        )
    except OAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    await states.record(auth.session, state=request_.state, purpose="reconnect")

    set_oauth_cookie(
        response,
        OAuthFlow(
            state=request_.state,
            code_verifier=request_.code_verifier,
            purpose="reconnect",
            account_id=str(account.id),
        ),
    )
    log.info("account.reconnect_started", account_id=str(account.id))
    return ReconnectResponse(authorize_url=request_.authorize_url)


@router.delete(
    "/{account_id}",
    response_model=DisconnectResponse,
    dependencies=[Depends(require_csrf)],
    summary="Disconnect an account",
)
async def disconnect(
    account_id: UUID,
    auth: AuthContext,
    client: OAuth,
    purge: Annotated[Literal["now", "30d"], Query()] = "30d",
) -> DisconnectResponse:
    """Revoke at Google, delete the credential now, schedule the data purge.

    The credential goes immediately whichever retention is chosen. Holding a
    decryptable token for thirty days after someone asked to disconnect is
    not retention (open decision O5).
    """
    try:
        account = await service.get_account(auth.session, account_id)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account") from exc

    view = await service.disconnect(
        auth.session, account=account, client=client, purge_now=purge == "now"
    )
    return DisconnectResponse(id=view.id, status=view.status.value, purge_after=view.purge_after)
