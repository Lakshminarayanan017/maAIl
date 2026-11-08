"""The phase 2 blocking gates, and thread merging.

> Blocking gates. Repeated and interrupted sync produces identical local
> state. No duplicate messages. Quota limiter prevents
> `userRateLimitExceeded`. A dead history cursor recovers via bounded
> reconciliation.
> (09-execution-plan.md, phase 2)

Only Gmail is faked. The store, the normaliser, the merge logic, RLS and
the state machine are the real ones, against a real Postgres.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.tenancy import tenant_session
from app.database.models.thread import EmailMessage, EmailThread
from app.modules.sync import engine as sync_engine
from app.modules.sync.quota import BUCKET_CAPACITY
from tests.fakes import FakeGmail, FakeMessage
from tests.helpers import sign_in

pytestmark = pytest.mark.integration


async def connected(api: object) -> tuple[UUID, UUID]:
    """Sign in and return ``(user_id, account_id)``."""
    await sign_in(api)
    user_id = UUID((await api.get("/api/v1/auth/session")).json()["user"]["id"])  # type: ignore[attr-defined]
    account_id = UUID((await api.get("/api/v1/accounts")).json()[0]["id"])  # type: ignore[attr-defined]
    return user_id, account_id


async def run_sync(
    user_id: UUID, account_id: UUID, gmail: FakeGmail, fake_oauth: object, **kwargs: object
) -> object:
    sync_engine._progress.pop(account_id, None)
    return await sync_engine.sync_account(
        user_id=user_id,
        account_id=account_id,
        provider_factory=gmail.factory(),
        oauth_client=fake_oauth,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


async def snapshot(user_id: UUID, account_id: UUID) -> dict[str, object]:
    """Everything about the local state that a repeat sync must not change."""
    async with tenant_session(user_id) as session:
        messages = (
            await session.execute(
                select(
                    EmailMessage.provider_message_id,
                    EmailMessage.subject,
                    EmailMessage.body_text,
                    EmailMessage.is_read,
                )
                .where(EmailMessage.account_id == account_id)
                .order_by(EmailMessage.provider_message_id)
            )
        ).all()
        threads = (
            await session.execute(
                select(EmailThread.provider_thread_id, EmailThread.message_count)
                .where(
                    EmailThread.account_id == account_id,
                    EmailThread.merged_into_thread_id.is_(None),
                )
                .order_by(EmailThread.provider_thread_id)
            )
        ).all()
    return {
        "messages": [tuple(row) for row in messages],
        "threads": [tuple(row) for row in threads],
    }


MAILBOX = [
    FakeMessage("m1", "t1", subject="CI pipeline failed", rfc822="<ci-1@github.test>"),
    FakeMessage(
        "m2",
        "t1",
        subject="Re: CI pipeline failed",
        rfc822="<ci-2@github.test>",
        in_reply_to="<ci-1@github.test>",
    ),
    FakeMessage(
        "m3",
        "t2",
        subject="Interview invite",
        rfc822="<hr-1@corp.test>",
        sender="recruiter@corp.test",
    ),
]


class TestIdempotence:
    """Gate: repeated and interrupted sync produces identical local state."""

    async def test_syncing_twice_changes_nothing(self, api: object, fake_oauth: object) -> None:
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX))

        await run_sync(user_id, account_id, gmail, fake_oauth)
        first = await snapshot(user_id, account_id)

        await run_sync(user_id, account_id, gmail, fake_oauth, full=True)
        second = await snapshot(user_id, account_id)

        assert first == second

    async def test_an_interrupted_sync_resumes_rather_than_restarts(
        self, api: object, fake_oauth: object, owner_engine: AsyncEngine
    ) -> None:
        """Progress lives in the rows, not in the process.

        Simulated by dropping the bodies the first run fetched: the second
        run must refill exactly those and leave everything else alone.
        """
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX))

        await run_sync(user_id, account_id, gmail, fake_oauth)
        complete = await snapshot(user_id, account_id)

        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE email_messages SET body_text = NULL, body_fetched_at = NULL "
                    "WHERE provider_message_id IN ('m2', 'm3')"
                )
            )

        calls_before = len(gmail.calls)
        await run_sync(user_id, account_id, gmail, fake_oauth, full=True)

        assert await snapshot(user_id, account_id) == complete
        # It refetched the two it was missing, not the whole mailbox again.
        body_calls = [c for c in gmail.calls[calls_before:] if c == "messages.get:full"]
        assert len(body_calls) == 2

    async def test_no_duplicate_messages(self, api: object, fake_oauth: object) -> None:
        """Gate: no duplicate messages.

        The unique constraint is the mechanism, so this also proves the
        upsert takes the conflict path rather than raising.
        """
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX))

        for _ in range(3):
            await run_sync(user_id, account_id, gmail, fake_oauth, full=True)

        async with tenant_session(user_id) as session:
            total = await session.scalar(
                select(func.count(EmailMessage.id)).where(EmailMessage.account_id == account_id)
            )
            distinct = await session.scalar(
                select(func.count(func.distinct(EmailMessage.provider_message_id))).where(
                    EmailMessage.account_id == account_id
                )
            )

        assert total == distinct == len(MAILBOX)


class TestQuota:
    """Gate: the limiter prevents `userRateLimitExceeded`."""

    async def test_a_sync_never_outruns_the_per_minute_budget(
        self, api: object, fake_oauth: object
    ) -> None:
        from app.modules.sync.quota import limiter

        user_id, account_id = await connected(api)
        limiter.reset(account_id)

        mailbox = [FakeMessage(f"m{i}", f"t{i}", rfc822=f"<m{i}@x.test>") for i in range(40)]
        gmail = FakeGmail(mailbox)

        await run_sync(user_id, account_id, gmail, fake_oauth)

        # 40 metadata fetches at 20 plus 40 full fetches at 60 is 3,200
        # units, which fits inside a minute's 6,000 without waiting. The
        # point is that the spend is counted at all, and stays under.
        assert gmail.units_spent <= BUCKET_CAPACITY
        assert limiter.waited_total(account_id) == 0

    async def test_exceeding_the_budget_waits_instead_of_failing(self) -> None:
        """The bucket blocks. Gmail answering 429 is the thing it prevents."""
        from app.modules.sync.quota import TokenBucket

        bucket = TokenBucket(capacity=100, refill_per_second=100.0, tokens=100.0)
        await bucket.acquire(100)
        assert bucket.wait_time(50) == pytest.approx(0.5, abs=0.05)

    async def test_a_single_call_larger_than_the_bucket_is_refused(self) -> None:
        """Rather than waiting for ever on tokens that can never arrive."""
        from app.modules.sync.quota import TokenBucket

        bucket = TokenBucket(capacity=100, refill_per_second=100.0, tokens=100.0)
        with pytest.raises(ValueError, match="exceeds the bucket"):
            await bucket.acquire(101)


class TestReconciliation:
    """Gate: a dead history cursor recovers via bounded reconciliation."""

    async def test_a_stale_cursor_reconciles_rather_than_resyncing(
        self, api: object, fake_oauth: object, owner_engine: AsyncEngine
    ) -> None:
        user_id, account_id = await connected(api)

        gmail = FakeGmail(list(MAILBOX))
        await run_sync(user_id, account_id, gmail, fake_oauth)

        # Gmail forgets the cursor, and a message arrives while it is gone.
        gmail.stale_cursor = True
        gmail.messages["m4"] = FakeMessage(
            "m4", "t3", subject="Arrived during the gap", rfc822="<new@x.test>"
        )
        calls_before = len(gmail.calls)

        progress = await run_sync(user_id, account_id, gmail, fake_oauth)

        assert progress.phase == "active"  # type: ignore[attr-defined]

        async with tenant_session(user_id) as session:
            found = await session.scalar(
                select(EmailMessage.subject).where(
                    EmailMessage.account_id == account_id,
                    EmailMessage.provider_message_id == "m4",
                )
            )
        assert found == "Arrived during the gap"

        # Bounded: it diffed a window and fetched the one missing message.
        # A blind resync would have refetched all four.
        new_full_fetches = [c for c in gmail.calls[calls_before:] if c == "messages.get:full"]
        assert len(new_full_fetches) == 1

    async def test_reconciliation_soft_deletes_what_is_gone(
        self, api: object, fake_oauth: object
    ) -> None:
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX))
        await run_sync(user_id, account_id, gmail, fake_oauth)

        gmail.stale_cursor = True
        del gmail.messages["m3"]

        await run_sync(user_id, account_id, gmail, fake_oauth)

        async with tenant_session(user_id) as session:
            deleted_at = await session.scalar(
                select(EmailMessage.deleted_at).where(
                    EmailMessage.account_id == account_id,
                    EmailMessage.provider_message_id == "m3",
                )
            )
        # Soft: Gmail's delete is often a mistake, and the row is cheap.
        assert deleted_at is not None

    async def test_the_cursor_is_reanchored_afterwards(
        self, api: object, fake_oauth: object
    ) -> None:
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX), history_id="5000")
        await run_sync(user_id, account_id, gmail, fake_oauth)

        gmail.stale_cursor = True
        gmail.history_id = "9999"
        await run_sync(user_id, account_id, gmail, fake_oauth)

        async with tenant_session(user_id) as session:
            from app.database.models.account import ConnectedAccount

            account = await session.get(ConnectedAccount, account_id)
            assert account is not None
            assert account.history_cursor == "9999"
            assert account.history_cursor_at is not None


class TestThreading:
    """Gmail's threadId is a hint, the References chain is evidence (gap A5)."""

    async def test_a_reply_lands_in_its_parents_thread(
        self, api: object, fake_oauth: object
    ) -> None:
        user_id, account_id = await connected(api)
        await run_sync(user_id, account_id, FakeGmail(list(MAILBOX)), fake_oauth)

        async with tenant_session(user_id) as session:
            rows = (
                await session.execute(
                    select(EmailThread.provider_thread_id, EmailThread.message_count).where(
                        EmailThread.account_id == account_id,
                        EmailThread.merged_into_thread_id.is_(None),
                    )
                )
            ).all()

        by_provider = dict(rows)
        assert by_provider["t1"] == 2
        assert by_provider["t2"] == 1

    async def test_two_threads_merge_when_the_chain_crosses_them(
        self, api: object, fake_oauth: object
    ) -> None:
        """Gmail split a conversation; the References chain reunites it."""
        user_id, account_id = await connected(api)

        split = [
            FakeMessage("a1", "tA", subject="Design review", rfc822="<a1@x.test>"),
            FakeMessage("b1", "tB", subject="Design review", rfc822="<b1@x.test>"),
            # Arrives under tB but replies to a message in tA.
            FakeMessage(
                "b2",
                "tB",
                subject="Re: Design review",
                rfc822="<b2@x.test>",
                in_reply_to="<a1@x.test>",
                references="<a1@x.test> <b1@x.test>",
            ),
        ]
        await run_sync(user_id, account_id, FakeGmail(split), fake_oauth)

        async with tenant_session(user_id) as session:
            survivors = (
                await session.execute(
                    select(EmailThread.id, EmailThread.message_count).where(
                        EmailThread.account_id == account_id,
                        EmailThread.merged_into_thread_id.is_(None),
                    )
                )
            ).all()
            merged = (
                await session.execute(
                    select(func.count(EmailThread.id)).where(
                        EmailThread.account_id == account_id,
                        EmailThread.merged_into_thread_id.is_not(None),
                    )
                )
            ).scalar()

        assert len(survivors) == 1, f"expected one conversation, got {survivors}"
        assert survivors[0][1] == 3
        # The absorbed row stays, so anything derived against it keeps its
        # audit trail.
        assert merged == 1

    async def test_a_missing_message_does_not_fail_the_batch(
        self, api: object, fake_oauth: object
    ) -> None:
        """Gap A7. Messages are deleted between the list and the get."""
        user_id, account_id = await connected(api)
        gmail = FakeGmail(list(MAILBOX), missing={"m2"})

        progress = await run_sync(user_id, account_id, gmail, fake_oauth)

        assert progress.phase == "active"  # type: ignore[attr-defined]
        assert progress.misses > 0  # type: ignore[attr-defined]

        async with tenant_session(user_id) as session:
            kept = await session.scalar(
                select(func.count(EmailMessage.id)).where(EmailMessage.account_id == account_id)
            )
        assert kept == 2
