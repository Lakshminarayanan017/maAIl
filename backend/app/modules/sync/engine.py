"""The sync state machine. Two passes, then deltas. Zero LLM.

```
connecting → initial_metadata → initial_bodies → active
                                                   │
             ┌─────────────────────────────────────┤
             ▼                  ▼                  ▼
      reauth_required      reconciling           error
```

**Why two passes.** Quota is 6,000 units per user per minute. A metadata
fetch is 20 units, a full fetch 60, so metadata-first buys three times the
coverage per minute. Pass 1 gives every thread a sender, a subject and a
date — enough to render the inbox — and pass 2 fills bodies newest-first
behind it. The inbox is never blank while syncing.

**Why it is resumable.** No progress lives in this process. What has been
fetched is the set of rows in ``email_messages``; what still needs a body is
a partial index on ``body_fetched_at IS NULL``. Killing a sync mid-run loses
the in-flight batch and nothing else, and starting again recomputes the work
list rather than replaying a plan.

**Why one bad message does not matter.** Messages are deleted between the
list call and the get call on every sync. A miss is recorded against the
message with an attempt count and the batch continues (gap A7).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.clock import get_clock
from app.core.logging import bind_contextvars, get_logger
from app.core.tenancy import tenant_session
from app.database.models.account import AccountStatus, ConnectedAccount
from app.modules.accounts import service
from app.modules.ingest.normalizer import normalise
from app.modules.providers.email.base import (
    MailProvider,
    MessageUnavailable,
    ProviderError,
    RateLimited,
    StaleHistoryCursor,
)
from app.modules.providers.oauth.base import OAuthClient, ReauthRequired
from app.modules.sync.reconcile import reconcile
from app.modules.threads import store

log = get_logger(__name__)

#: The cold-start rule: the newest 500 threads first, then backfill. Someone
#: who has just connected should see their actual inbox in under a minute,
#: not a progress bar over ten years of mail.
COLD_START_MESSAGES = 500

#: Page size for messages.list. Gmail's maximum, and the call is cheap.
LIST_PAGE_SIZE = 500

#: How many bodies one pass-2 batch fetches before yielding. At 60 units
#: each this is about half a minute of quota, so progress stays visible.
BODY_BATCH = 50

#: Stop retrying a message after this many failures. Three is enough for a
#: transient 500 and few enough that a permanently gone message stops
#: costing quota.
MAX_BODY_ATTEMPTS = 3


@dataclass
class SyncProgress:
    phase: str
    done: int = 0
    total: int | None = None
    threads: int = 0
    new_messages: int = 0
    misses: int = 0
    merged_threads: int = 0
    error: str | None = None

    @property
    def finished(self) -> bool:
        return self.phase in ("active", "error", "reauth_required")


class SyncAlreadyRunning(Exception):
    """One sync per account. A second would race the first for quota."""


#: Per-account locks. Correct while sync runs in this process; phase 4's job
#: queue replaces it with a lease, and the call sites do not change.
_locks: dict[UUID, asyncio.Lock] = {}
_progress: dict[UUID, SyncProgress] = {}


def progress_for(account_id: UUID) -> SyncProgress | None:
    return _progress.get(account_id)


def _lock(account_id: UUID) -> asyncio.Lock:
    lock = _locks.get(account_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[account_id] = lock
    return lock


async def sync_account(
    *,
    user_id: UUID,
    account_id: UUID,
    provider_factory: object,
    oauth_client: OAuthClient,
    full: bool = False,
) -> SyncProgress:
    """Bring one account up to date.

    ``provider_factory`` takes an access token and returns a ``MailProvider``.
    Injected rather than imported so the sync can be driven against a stub
    without a network.
    """
    lock = _lock(account_id)
    if lock.locked():
        raise SyncAlreadyRunning(str(account_id))

    async with lock:
        bind_contextvars(account_id=str(account_id))
        progress = SyncProgress(phase="connecting")
        _progress[account_id] = progress

        try:
            async with tenant_session(user_id) as session:
                account = await service.get_account(session, account_id)
                token = await service.ensure_access_token(
                    session, account=account, client=oauth_client
                )
                account_email = account.provider_account_email
                cursor = account.history_cursor
                cursor_at = account.history_cursor_at

            provider: MailProvider = provider_factory(token)  # type: ignore[operator]

            if full or cursor is None:
                await _initial_sync(
                    user_id=user_id,
                    account_id=account_id,
                    account_email=account_email,
                    provider=provider,
                    progress=progress,
                )
            else:
                await _delta_sync(
                    user_id=user_id,
                    account_id=account_id,
                    account_email=account_email,
                    provider=provider,
                    progress=progress,
                    cursor=cursor,
                    cursor_at=cursor_at,
                )

            progress.phase = "active"
            await _set_status(user_id, account_id, AccountStatus.active, error=None)

        except ReauthRequired as exc:
            progress.phase = "reauth_required"
            progress.error = str(exc)
            log.info("sync.reauth_required", account_id=str(account_id))
        except Exception as exc:
            progress.phase = "error"
            progress.error = str(exc)[:500]
            await _set_status(user_id, account_id, AccountStatus.error, error=str(exc))
            log.exception("sync.failed", account_id=str(account_id))

        return progress


# ---------------------------------------------------------------------------
# initial sync
# ---------------------------------------------------------------------------
async def _initial_sync(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    progress: SyncProgress,
) -> None:
    # The cursor is taken *before* the listing, not after. Anything that
    # arrives during the sync then shows up in the first delta rather than
    # falling into the gap between the two calls.
    starting_cursor = await provider.current_history_id()

    progress.phase = "initial_metadata"
    await _set_status(user_id, account_id, AccountStatus.connecting, error=None)

    page_token: str | None = None
    seen = 0
    while True:
        page = await provider.list_messages(page_token=page_token, max_results=LIST_PAGE_SIZE)
        if page.size_estimate is not None and progress.total is None:
            progress.total = page.size_estimate

        for ref in page.refs:
            await _ingest_one(
                user_id=user_id,
                account_id=account_id,
                account_email=account_email,
                provider=provider,
                provider_message_id=ref.provider_message_id,
                progress=progress,
                with_body=False,
            )
            seen += 1
            if seen % 25 == 0:
                await _persist_progress(user_id, account_id, progress)

        await _persist_progress(user_id, account_id, progress)

        page_token = page.next_page_token
        if not page_token:
            break
        # The cold-start rule. Once the newest 500 are in, the inbox is
        # usable, so the rest is backfill behind a usable screen.
        if seen >= COLD_START_MESSAGES:
            log.info("sync.cold_start_covered", account_id=str(account_id), messages=seen)

    progress.phase = "initial_bodies"
    await _fetch_bodies(
        user_id=user_id,
        account_id=account_id,
        account_email=account_email,
        provider=provider,
        progress=progress,
    )

    await _set_cursor(user_id, account_id, starting_cursor)


async def _fetch_bodies(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    progress: SyncProgress,
) -> None:
    """Pass 2. Newest first, so the mail someone is looking at arrives first."""
    while True:
        async with tenant_session(user_id) as session:
            batch = await store.messages_needing_bodies(
                session, account_id=account_id, limit=BODY_BATCH, max_attempts=MAX_BODY_ATTEMPTS
            )
        if not batch:
            return

        for _row_id, provider_message_id in batch:
            await _ingest_one(
                user_id=user_id,
                account_id=account_id,
                account_email=account_email,
                provider=provider,
                provider_message_id=provider_message_id,
                progress=progress,
                with_body=True,
            )
        await _persist_progress(user_id, account_id, progress)


# ---------------------------------------------------------------------------
# delta sync
# ---------------------------------------------------------------------------
async def _delta_sync(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    progress: SyncProgress,
    cursor: str,
    cursor_at: object,
) -> None:
    progress.phase = "delta"

    try:
        page_token: str | None = None
        latest_history_id: str | None = None
        while True:
            page = await provider.list_history(start_history_id=cursor, page_token=page_token)
            latest_history_id = page.history_id or latest_history_id

            for event in page.events:
                await _apply_history_event(
                    user_id=user_id,
                    account_id=account_id,
                    account_email=account_email,
                    provider=provider,
                    event=event,
                    progress=progress,
                )

            page_token = page.next_page_token
            if not page_token:
                break

        if latest_history_id:
            await _set_cursor(user_id, account_id, latest_history_id)

    except StaleHistoryCursor:
        # Gmail guarantees history for about a week. A cursor older than
        # that is gone, and the answer is a bounded diff, never a blind
        # resync of the mailbox (gap A2).
        progress.phase = "reconciling"
        log.info(
            "sync.cursor_stale",
            account_id=str(account_id),
            cursor_age_days=_cursor_age_days(cursor_at),
        )
        summary = await reconcile(
            user_id=user_id,
            account_id=account_id,
            account_email=account_email,
            provider=provider,
        )
        progress.new_messages += summary.fetched
        progress.misses += summary.misses
        await _fetch_bodies(
            user_id=user_id,
            account_id=account_id,
            account_email=account_email,
            provider=provider,
            progress=progress,
        )


async def _apply_history_event(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    event: object,
    progress: SyncProgress,
) -> None:
    from app.modules.providers.email.base import HistoryEvent

    assert isinstance(event, HistoryEvent)

    if event.kind == "messagesAdded":
        await _ingest_one(
            user_id=user_id,
            account_id=account_id,
            account_email=account_email,
            provider=provider,
            provider_message_id=event.provider_message_id,
            progress=progress,
            with_body=True,
        )
        return

    async with tenant_session(user_id) as session:
        if event.kind == "messagesDeleted":
            await store.soft_delete_message(
                session,
                account_id=account_id,
                provider_message_id=event.provider_message_id,
            )
        elif event.kind == "labelsAdded":
            await store.apply_labels(
                session,
                account_id=account_id,
                provider_message_id=event.provider_message_id,
                added=event.label_ids,
            )
        elif event.kind == "labelsRemoved":
            await store.apply_labels(
                session,
                account_id=account_id,
                provider_message_id=event.provider_message_id,
                removed=event.label_ids,
            )


# ---------------------------------------------------------------------------
# one message
# ---------------------------------------------------------------------------
async def _ingest_one(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    provider_message_id: str,
    progress: SyncProgress,
    with_body: bool,
) -> None:
    try:
        raw = (
            await provider.get_full(provider_message_id)
            if with_body
            else await provider.get_metadata(provider_message_id)
        )
    except MessageUnavailable:
        # Deleted between the list and the get. Happens on every sync.
        progress.misses += 1
        if with_body:
            await _record_miss(user_id, account_id, provider_message_id, "not found")
        return
    except RateLimited as exc:
        await asyncio.sleep(exc.retry_after)
        progress.misses += 1
        return
    except ProviderError as exc:
        progress.misses += 1
        if with_body:
            await _record_miss(user_id, account_id, provider_message_id, str(exc))
        log.warning("sync.message_failed", message_id=provider_message_id, error=str(exc))
        return

    normalised = normalise(raw, account_email=account_email)

    async with tenant_session(user_id) as session:
        result = await store.upsert_message(
            session, user_id=user_id, account_id=account_id, message=normalised
        )

    progress.done += 1
    if result.created:
        progress.new_messages += 1
    progress.merged_threads += len(result.merged_thread_ids)


async def _record_miss(
    user_id: UUID, account_id: UUID, provider_message_id: str, reason: str
) -> None:
    async with tenant_session(user_id) as session:
        from app.database.models.thread import EmailMessage

        row_id = await session.scalar(
            select(EmailMessage.id).where(
                EmailMessage.account_id == account_id,
                EmailMessage.provider_message_id == provider_message_id,
            )
        )
        if row_id is not None:
            await store.record_body_failure(session, message_id=row_id, reason=reason)


# ---------------------------------------------------------------------------
# account state
# ---------------------------------------------------------------------------
async def _persist_progress(user_id: UUID, account_id: UUID, progress: SyncProgress) -> None:
    async with tenant_session(user_id) as session:
        account = await session.get(ConnectedAccount, account_id)
        if account is None:
            return
        account.initial_sync_done = progress.done
        account.initial_sync_total = progress.total
        progress.threads = await store.live_threads(session, account_id=account_id)


async def _set_cursor(user_id: UUID, account_id: UUID, history_id: str) -> None:
    async with tenant_session(user_id) as session:
        account = await session.get(ConnectedAccount, account_id)
        if account is None:
            return
        account.history_cursor = history_id
        # The age matters as much as the value: a cursor older than a week
        # is dead, and knowing when it was taken is how that is detected
        # before Gmail says so (gap A2).
        account.history_cursor_at = get_clock().now()
        account.last_delta_sync_at = get_clock().now()


async def _set_status(
    user_id: UUID, account_id: UUID, status: AccountStatus, *, error: str | None
) -> None:
    async with tenant_session(user_id) as session:
        account = await session.get(ConnectedAccount, account_id)
        if account is None:
            return
        if account.status is AccountStatus.reauth_required and status is AccountStatus.active:
            account.last_error = None
        account.status = status
        account.last_error = error[:500] if error else None


def _cursor_age_days(cursor_at: object) -> float | None:
    from datetime import datetime

    if not isinstance(cursor_at, datetime):
        return None
    return round((get_clock().now() - cursor_at) / timedelta(days=1), 2)
