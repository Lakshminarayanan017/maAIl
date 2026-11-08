"""The connected-account lifecycle.

Every function here takes a session that already has a tenant armed, except
``upsert_user``, which runs before one can exist.

The shape worth noticing is ``ensure_access_token``. It is the only place that
decrypts a refresh token, and the only place that decides an account has moved
to ``reauth_required``. A Testing-mode refresh token dies after about a week
(gap A3), so that transition is the normal weekly case, not an incident: it is
recorded, it is visible in the UI, and it never raises into a sync job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.crypto import SealedCredential, TokenPair, open_tokens, seal_tokens
from app.core.logging import get_logger
from app.database.models.account import AccountStatus, ConnectedAccount, OAuthCredential
from app.modules.providers.oauth.base import OAuthClient, ReauthRequired, TokenGrant
from app.modules.providers.oauth.google import missing_scopes

log = get_logger(__name__)

#: Refresh this far before expiry rather than on it, so a long request does
#: not start with a valid token and finish with an expired one.
REFRESH_SKEW = timedelta(minutes=5)

#: The UI starts warning this far ahead of the refresh-token expiry, which in
#: Testing mode is the weekly re-authorisation.
REAUTH_WARNING_WINDOW = timedelta(days=2)

_CREATE_USER = text("SELECT app_create_user(:email, :name, :timezone)")


@dataclass(frozen=True)
class AccountView:
    """What the API returns. No tokens, no ciphertext, no key version."""

    id: UUID
    email: str
    provider: str
    status: AccountStatus
    granted_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]
    refresh_expires_at: datetime | None
    connected_at: datetime
    last_error: str | None
    initial_sync_total: int | None
    initial_sync_done: int
    last_delta_sync_at: datetime | None
    disconnected_at: datetime | None
    purge_after: datetime | None

    @property
    def needs_reconnect(self) -> bool:
        return self.status is AccountStatus.reauth_required

    @property
    def expires_soon(self) -> bool:
        if self.refresh_expires_at is None or self.status is not AccountStatus.active:
            return False
        return self.refresh_expires_at - get_clock().now() <= REAUTH_WARNING_WINDOW


class AccountNotFound(Exception):
    """No such account for this user. Same answer as someone else's account."""


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
async def upsert_user(
    session: AsyncSession, *, email: str, name: str | None, timezone: str = "UTC"
) -> UUID:
    """Find or create the user behind a Google identity.

    Runs with no tenant armed, through the SECURITY DEFINER function from
    migration 0001, because a row cannot satisfy a policy that compares
    against an identity the row is about to establish.
    """
    result = await session.execute(
        _CREATE_USER, {"email": email, "name": name, "timezone": timezone}
    )
    user_id = result.scalar_one()
    return UUID(str(user_id))


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def to_view(account: ConnectedAccount) -> AccountView:
    credential = account.credential
    return AccountView(
        id=account.id,
        email=account.provider_account_email,
        provider=account.provider,
        status=account.status,
        granted_scopes=tuple(account.granted_scopes),
        missing_scopes=missing_scopes(account.granted_scopes),
        refresh_expires_at=credential.refresh_expires_at if credential else None,
        connected_at=account.created_at,
        last_error=account.last_error,
        initial_sync_total=account.initial_sync_total,
        initial_sync_done=account.initial_sync_done,
        last_delta_sync_at=account.last_delta_sync_at,
        disconnected_at=account.disconnected_at,
        purge_after=account.purge_after,
    )


async def list_accounts(
    session: AsyncSession, *, include_disconnected: bool = False
) -> list[AccountView]:
    """RLS scopes this to the armed tenant; no WHERE user_id here on purpose."""
    statement = select(ConnectedAccount).order_by(ConnectedAccount.created_at)
    if not include_disconnected:
        statement = statement.where(ConnectedAccount.status != AccountStatus.disconnected)
    accounts = (await session.scalars(statement)).all()
    return [to_view(account) for account in accounts]


async def get_account(session: AsyncSession, account_id: UUID) -> ConnectedAccount:
    account = await session.get(ConnectedAccount, account_id)
    if account is None:
        # RLS already filtered another tenant's row out, so "not yours" and
        # "does not exist" arrive here identically. Answering the same way is
        # what stops this endpoint confirming that an id exists.
        raise AccountNotFound(str(account_id))
    return account


# ---------------------------------------------------------------------------
# connecting
# ---------------------------------------------------------------------------
async def attach_grant(
    session: AsyncSession,
    *,
    user_id: UUID,
    provider: str,
    email: str,
    grant: TokenGrant,
) -> ConnectedAccount:
    """Create or re-arm a connection from a fresh grant.

    Reconnecting an existing account reuses the row, so its id, its history
    cursor and everything derived from it survive a weekly re-authorisation.
    Losing them would mean re-syncing a mailbox every seven days.
    """
    existing = await session.scalar(
        select(ConnectedAccount).where(
            ConnectedAccount.user_id == user_id,
            ConnectedAccount.provider == provider,
            ConnectedAccount.provider_account_email == email,
        )
    )

    absent = missing_scopes(grant.granted_scopes)
    status = AccountStatus.error if absent else AccountStatus.active

    if existing is None:
        account = ConnectedAccount(
            user_id=user_id,
            provider=provider,
            provider_account_email=email,
            status=status,
            granted_scopes=list(grant.granted_scopes),
        )
        session.add(account)
        await session.flush()
    else:
        account = existing
        account.status = status
        account.granted_scopes = list(grant.granted_scopes)
        account.disconnected_at = None
        account.purge_after = None

    account.last_error = "Missing permission: " + ", ".join(absent) if absent else None

    assert grant.refresh_token is not None  # exchange_code guarantees it
    await _store_credential(
        session,
        account=account,
        tokens=TokenPair(access_token=grant.access_token, refresh_token=grant.refresh_token),
        access_expires_at=grant.access_expires_at,
        refresh_expires_at=grant.refresh_expires_at,
    )

    log.info(
        "account.connected",
        account_id=str(account.id),
        provider=provider,
        status=status.value,
        missing_scopes=list(absent),
    )
    return account


async def _store_credential(
    session: AsyncSession,
    *,
    account: ConnectedAccount,
    tokens: TokenPair,
    access_expires_at: datetime | None,
    refresh_expires_at: datetime | None,
) -> None:
    sealed = seal_tokens(
        account.id,
        tokens,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )
    credential = await session.get(OAuthCredential, account.id)
    if credential is None:
        credential = OAuthCredential(account_id=account.id, user_id=account.user_id)
        session.add(credential)

    credential.access_ciphertext = sealed.access_ciphertext
    credential.refresh_ciphertext = sealed.refresh_ciphertext
    credential.dek_wrapped = sealed.dek_wrapped
    credential.key_version = sealed.key_version
    credential.access_expires_at = access_expires_at
    # A refresh does not reissue the refresh token, so its expiry is only
    # overwritten when a new one actually arrived.
    if refresh_expires_at is not None:
        credential.refresh_expires_at = refresh_expires_at
    credential.updated_at = get_clock().now()
    await session.flush()


# ---------------------------------------------------------------------------
# using
# ---------------------------------------------------------------------------
async def ensure_access_token(
    session: AsyncSession, *, account: ConnectedAccount, client: OAuthClient
) -> str:
    """A usable access token, refreshing first if the current one is stale.

    Raises ``ReauthRequired`` after recording the state on the account, so a
    caller that ignores the exception still leaves the system telling the
    truth about why nothing is syncing.
    """
    credential = await session.get(OAuthCredential, account.id)
    if credential is None:
        await mark_reauth_required(session, account=account, reason="No stored credential")
        raise ReauthRequired("This account has no stored credential")

    sealed = SealedCredential(
        access_ciphertext=credential.access_ciphertext,
        refresh_ciphertext=credential.refresh_ciphertext,
        dek_wrapped=credential.dek_wrapped,
        key_version=credential.key_version,
    )
    tokens = open_tokens(account.id, sealed)

    now = get_clock().now()
    fresh_enough = (
        credential.access_expires_at is not None
        and credential.access_expires_at - now > REFRESH_SKEW
    )
    if fresh_enough:
        return tokens.access_token

    try:
        grant = await client.refresh(refresh_token=tokens.refresh_token)
    except ReauthRequired as exc:
        await mark_reauth_required(session, account=account, reason=str(exc))
        raise

    await _store_credential(
        session,
        account=account,
        tokens=TokenPair(
            access_token=grant.access_token,
            refresh_token=grant.refresh_token or tokens.refresh_token,
        ),
        access_expires_at=grant.access_expires_at,
        refresh_expires_at=grant.refresh_expires_at,
    )

    if account.status is AccountStatus.reauth_required:
        account.status = AccountStatus.active
        account.last_error = None

    log.info("account.token_refreshed", account_id=str(account.id))
    return grant.access_token


async def mark_reauth_required(
    session: AsyncSession, *, account: ConnectedAccount, reason: str
) -> None:
    """The weekly case, recorded rather than raised.

    Sync fails soft into this state. The UI shows a persistent banner, the
    user reconnects, and the account keeps its id and its cursor.
    """
    account.status = AccountStatus.reauth_required
    account.last_error = reason[:500]
    await session.flush()
    log.info("account.reauth_required", account_id=str(account.id))


# ---------------------------------------------------------------------------
# disconnecting
# ---------------------------------------------------------------------------
async def disconnect(
    session: AsyncSession,
    *,
    account: ConnectedAccount,
    client: OAuthClient,
    purge_now: bool,
    retention_days: int = 30,
) -> AccountView:
    """Revoke at Google, drop the credential, and schedule the data purge.

    The credential row goes immediately whatever the retention choice. Keeping
    a decryptable token for thirty days after someone asked to disconnect is
    not retention, it is a liability (open decision O5).
    """
    credential = await session.get(OAuthCredential, account.id)
    if credential is not None:
        try:
            tokens = open_tokens(
                account.id,
                SealedCredential(
                    access_ciphertext=credential.access_ciphertext,
                    refresh_ciphertext=credential.refresh_ciphertext,
                    dek_wrapped=credential.dek_wrapped,
                    key_version=credential.key_version,
                ),
            )
            # Gap A4: Google silently drops the oldest of a hundred live
            # refresh tokens per client, so leaving grants behind in
            # development eventually breaks a real one.
            await client.revoke(token=tokens.refresh_token)
        except Exception as exc:
            log.warning("account.revoke_failed", account_id=str(account.id), error=str(exc))
        await session.delete(credential)

    now = get_clock().now()
    account.status = AccountStatus.disconnected
    account.disconnected_at = now
    account.purge_after = now if purge_now else now + timedelta(days=retention_days)
    account.history_cursor = None
    account.history_cursor_at = None
    account.last_error = None
    await session.flush()

    log.info("account.disconnected", account_id=str(account.id), purge_now=purge_now)
    return to_view(account)


async def clear_credentials_for_user(session: AsyncSession, *, user_id: UUID) -> int:
    """Used by the tests and, later, by account deletion."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(ConnectedAccount)
            .where(ConnectedAccount.user_id == user_id)
            .values(status=AccountStatus.disconnected)
        ),
    )
    return result.rowcount or 0
