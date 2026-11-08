"""Bounded reconciliation. Never a blind full resync.

Gmail guarantees `historyId` retention for only about a week, so a cursor
older than that returns 404 and is gone for good. The obvious response — re-
list the whole mailbox — costs tens of thousands of quota units and most of
an hour for an account that is probably a handful of messages out of date.

So this diffs a window instead. List the remote ids inside the window, read
the local ids inside the same window, fetch what is missing and soft-delete
what is gone. The window is bounded, so the cost is bounded, and it is
widened only when the evidence says the cursor was older than it.

Gap A2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.core.clock import get_clock
from app.core.logging import get_logger
from app.core.tenancy import tenant_session
from app.modules.providers.email.base import MailProvider
from app.modules.threads import store

log = get_logger(__name__)

#: A week of Gmail history retention, plus a wide margin for a laptop that
#: was shut for a holiday. Still a diff of days, not of a mailbox.
DEFAULT_WINDOW_DAYS = 30

#: Past this, re-listing the window stops being cheaper than accepting a
#: gap, so the window is capped and the shortfall is logged rather than
#: silently costing an hour of quota.
MAX_WINDOW_DAYS = 180


@dataclass
class ReconcileSummary:
    window_days: int
    remote: int
    local: int
    fetched: int
    deleted: int
    misses: int = 0


async def reconcile(
    *,
    user_id: UUID,
    account_id: UUID,
    account_email: str,
    provider: MailProvider,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cursor_age_days: float | None = None,
) -> ReconcileSummary:
    """Diff a bounded window and re-anchor the cursor."""
    if cursor_age_days is not None:
        # If the cursor was older than the default window, the window has
        # to cover it or the diff misses exactly the messages it exists to
        # find.
        window_days = max(window_days, int(cursor_age_days) + 2)
    window_days = min(window_days, MAX_WINDOW_DAYS)

    since = get_clock().now() - timedelta(days=window_days)

    remote_ids: set[str] = set()
    page_token: str | None = None
    while True:
        page = await provider.list_messages(page_token=page_token, after=since)
        remote_ids.update(ref.provider_message_id for ref in page.refs)
        page_token = page.next_page_token
        if not page_token:
            break

    async with tenant_session(user_id) as session:
        local_ids = await store.known_message_ids(session, account_id=account_id, after=since)

    missing = remote_ids - local_ids
    vanished = local_ids - remote_ids

    summary = ReconcileSummary(
        window_days=window_days,
        remote=len(remote_ids),
        local=len(local_ids),
        fetched=0,
        deleted=0,
    )

    from app.modules.ingest.normalizer import normalise
    from app.modules.providers.email.base import MessageUnavailable, ProviderError

    for provider_message_id in sorted(missing):
        try:
            raw = await provider.get_full(provider_message_id)
        except (MessageUnavailable, ProviderError):
            summary.misses += 1
            continue
        normalised = normalise(raw, account_email=account_email)
        async with tenant_session(user_id) as session:
            await store.upsert_message(
                session, user_id=user_id, account_id=account_id, message=normalised
            )
        summary.fetched += 1

    for provider_message_id in sorted(vanished):
        async with tenant_session(user_id) as session:
            if await store.soft_delete_message(
                session, account_id=account_id, provider_message_id=provider_message_id
            ):
                summary.deleted += 1

    # Re-anchor only after the diff has been applied. Storing the new cursor
    # first would mean a crash mid-diff leaves a cursor that claims to cover
    # work that never happened.
    history_id = await provider.current_history_id()
    async with tenant_session(user_id) as session:
        from app.database.models.account import ConnectedAccount

        account = await session.get(ConnectedAccount, account_id)
        if account is not None:
            account.history_cursor = history_id
            account.history_cursor_at = get_clock().now()

    log.info(
        "sync.reconciled",
        account_id=str(account_id),
        window_days=window_days,
        remote=summary.remote,
        local=summary.local,
        fetched=summary.fetched,
        deleted=summary.deleted,
        misses=summary.misses,
    )
    return summary
