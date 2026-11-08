"""The thread and message store, including merge handling.

The interesting function is ``resolve_thread``. Gmail's ``threadId`` is the
first answer, not the final one: Gmail splits a thread when the subject
changes or the thread grows past a size cap, and regroups messages
retroactively. So a message's ``References`` chain is consulted too, and when
the two disagree the threads are merged (gap A5).

Merging picks the survivor by ``first_message_at`` and leaves the absorbed
row in place with ``merged_into_thread_id`` set. The row is cheap and
anything already derived against it keeps its audit trail.

Zero-LLM zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.logging import get_logger
from app.database.models.thread import EmailMessage, EmailThread, MessageAttachment
from app.modules.ingest.normalizer import NormalisedMessage

log = get_logger(__name__)

_REFRESH_TSV = text("SELECT refresh_thread_tsv(:thread_id)")


@dataclass(frozen=True)
class IngestResult:
    message_id: UUID
    thread_id: UUID
    created: bool
    merged_thread_ids: tuple[UUID, ...] = ()


async def resolve_thread(
    session: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    message: NormalisedMessage,
) -> tuple[EmailThread, tuple[UUID, ...]]:
    """Find or create the thread this message belongs in.

    Returns the thread and the ids of any threads merged into it on the way.
    """
    by_provider = await session.scalar(
        select(EmailThread).where(
            EmailThread.account_id == account_id,
            EmailThread.provider_thread_id == message.provider_thread_id,
        )
    )
    by_provider = await _follow_merges(session, by_provider)

    by_references = await _thread_from_references(session, account_id=account_id, message=message)
    by_references = await _follow_merges(session, by_references)

    merged: list[UUID] = []

    if by_provider is not None and by_references is not None:
        if by_provider.id != by_references.id:
            # Gmail and the RFC-822 chain disagree. One conversation is
            # sitting in two rows, so collapse it rather than letting the
            # disagreement persist into everything derived from it.
            survivor, absorbed = _pick_survivor(by_provider, by_references)
            await merge_threads(session, survivor=survivor, absorbed=absorbed)
            merged.append(absorbed.id)
            return survivor, tuple(merged)
        return by_provider, ()

    if by_provider is not None:
        return by_provider, ()

    if by_references is not None:
        # The chain found the conversation under a threadId Gmail has since
        # changed. Re-point the existing row instead of starting a new one.
        by_references.provider_thread_id = message.provider_thread_id
        return by_references, ()

    thread = EmailThread(
        user_id=user_id,
        account_id=account_id,
        provider_thread_id=message.provider_thread_id,
        subject=message.subject,
        subject_normalized=message.subject_normalized,
        participant_emails=[],
        provider_labels=[],
    )
    session.add(thread)
    await session.flush()
    return thread, ()


async def _thread_from_references(
    session: AsyncSession, *, account_id: UUID, message: NormalisedMessage
) -> EmailThread | None:
    """The thread holding any message this one claims to reply to."""
    hints = message.thread_hints
    if not hints:
        return None

    thread_id = await session.scalar(
        select(EmailMessage.thread_id)
        .where(
            EmailMessage.account_id == account_id,
            EmailMessage.rfc822_message_id.in_(hints),
        )
        .order_by(EmailMessage.sent_at.desc())
        .limit(1)
    )
    if thread_id is None:
        return None
    return await session.get(EmailThread, thread_id)


async def _follow_merges(
    session: AsyncSession, thread: EmailThread | None, *, depth: int = 8
) -> EmailThread | None:
    """Walk ``merged_into_thread_id`` to the surviving row.

    Bounded, because a cycle here would hang a sync, and a corrupt pointer
    is a better thing to notice than to loop on.
    """
    seen: set[UUID] = set()
    while thread is not None and thread.merged_into_thread_id is not None:
        if thread.id in seen or len(seen) >= depth:
            log.warning("thread.merge_chain_too_long", thread_id=str(thread.id))
            return thread
        seen.add(thread.id)
        thread = await session.get(EmailThread, thread.merged_into_thread_id)
    return thread


def _pick_survivor(a: EmailThread, b: EmailThread) -> tuple[EmailThread, EmailThread]:
    """The older conversation survives.

    By ``first_message_at``, falling back to ``created_at`` and then to the
    id, so the choice is stable: two workers reaching the same merge from
    opposite directions must pick the same survivor.
    """

    def key(thread: EmailThread) -> tuple[float, float, str]:
        first = thread.first_message_at.timestamp() if thread.first_message_at else float("inf")
        created = thread.created_at.timestamp() if thread.created_at else float("inf")
        return (first, created, str(thread.id))

    return (a, b) if key(a) <= key(b) else (b, a)


async def merge_threads(
    session: AsyncSession, *, survivor: EmailThread, absorbed: EmailThread
) -> None:
    """Move every message across and mark the absorbed thread."""
    if survivor.id == absorbed.id:
        return

    await session.execute(
        update(EmailMessage)
        .where(EmailMessage.thread_id == absorbed.id)
        .values(thread_id=survivor.id)
    )

    absorbed.merged_into_thread_id = survivor.id
    absorbed.updated_at = get_clock().now()

    survivor.provider_labels = sorted(set(survivor.provider_labels) | set(absorbed.provider_labels))
    await session.flush()
    await recount_thread(session, survivor)

    log.info(
        "thread.merged",
        survivor_id=str(survivor.id),
        absorbed_id=str(absorbed.id),
    )


async def upsert_message(
    session: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    message: NormalisedMessage,
) -> IngestResult:
    """Write a message, creating or extending its thread.

    Dedupe is the ``(account_id, provider_message_id)`` unique constraint,
    not a prior SELECT: two workers racing the same message resolve in the
    database rather than both deciding it is new.
    """
    thread, merged = await resolve_thread(
        session, user_id=user_id, account_id=account_id, message=message
    )

    values = {
        "user_id": user_id,
        "account_id": account_id,
        "thread_id": thread.id,
        "provider_message_id": message.provider_message_id,
        "rfc822_message_id": message.rfc822_message_id,
        "in_reply_to": message.in_reply_to,
        "references_ids": message.references_ids,
        "from_email": message.from_email,
        "from_name": message.from_name,
        "to_emails": message.to_emails,
        "cc_emails": message.cc_emails,
        "subject": message.subject,
        "sent_at": message.sent_at,
        "sender_tz_offset_min": message.sender_tz_offset_min,
        "snippet": message.snippet,
        "size_bytes": message.size_bytes,
        "is_from_user": message.is_from_user,
        "is_read": message.is_read,
        "provider_labels": message.provider_labels,
        "deleted_at": None,
    }
    if message.has_body:
        values["body_text"] = message.body_text
        values["body_text_stripped"] = message.body_text_stripped
        values["stripped_ratio"] = message.stripped_ratio
        values["body_fetched_at"] = get_clock().now()
        values["last_fetch_error"] = None

    statement = pg_insert(EmailMessage).values(**values)
    # A re-sync must converge, not accumulate: the same message seen twice
    # updates in place, and a metadata-only pass never clears a body the
    # full pass already stored.
    update_columns = {
        key: getattr(statement.excluded, key) for key in values if key not in ("user_id",)
    }
    # `xmax = 0` is true only for a row this statement inserted. It is the
    # one way to tell an insert from an update inside a single upsert, and
    # the sync's progress count depends on knowing which happened.
    upsert = statement.on_conflict_do_update(
        constraint="uq_messages_provider", set_=update_columns
    ).returning(EmailMessage.id, text("(xmax = 0) AS inserted"))

    row = (await session.execute(upsert)).one()
    message_id: UUID = row[0]
    created = bool(row[1])

    if message.has_body and message.attachments:
        await _replace_attachments(session, user_id=user_id, message_id=message_id, message=message)

    await recount_thread(session, thread)

    return IngestResult(
        message_id=message_id,
        thread_id=thread.id,
        created=created,
        merged_thread_ids=merged,
    )


async def _replace_attachments(
    session: AsyncSession,
    *,
    user_id: UUID,
    message_id: UUID,
    message: NormalisedMessage,
) -> None:
    for attachment in message.attachments:
        statement = pg_insert(MessageAttachment).values(
            user_id=user_id,
            message_id=message_id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            size_bytes=attachment.size_bytes,
            provider_attachment_id=attachment.provider_attachment_id,
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_attachment_provider",
                set_={
                    "filename": statement.excluded.filename,
                    "mime_type": statement.excluded.mime_type,
                    "size_bytes": statement.excluded.size_bytes,
                },
            )
        )


async def recount_thread(session: AsyncSession, thread: EmailThread) -> None:
    """Re-derive the thread's counters from its messages.

    Recomputed rather than incremented. An increment is correct until the
    first retry, the first merge or the first soft delete, and then it is
    quietly wrong for ever.
    """
    await session.flush()

    aggregate = (
        await session.execute(
            select(
                func.count(EmailMessage.id),
                func.count(EmailMessage.id).filter(EmailMessage.is_read.is_(False)),
                func.min(EmailMessage.sent_at),
                func.max(EmailMessage.sent_at),
            ).where(
                EmailMessage.thread_id == thread.id,
                EmailMessage.deleted_at.is_(None),
            )
        )
    ).one()

    participants = (
        await session.execute(
            select(EmailMessage.from_email, EmailMessage.to_emails, EmailMessage.cc_emails)
            .where(EmailMessage.thread_id == thread.id, EmailMessage.deleted_at.is_(None))
            .order_by(EmailMessage.sent_at)
        )
    ).all()

    seen: dict[str, None] = {}
    for from_email, to_emails, cc_emails in participants:
        for address in [from_email, *(to_emails or []), *(cc_emails or [])]:
            if address:
                seen.setdefault(str(address).lower(), None)

    labels = (
        (
            await session.execute(
                select(EmailMessage.provider_labels).where(
                    EmailMessage.thread_id == thread.id, EmailMessage.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )

    has_attachments = bool(
        await session.scalar(
            select(func.count(MessageAttachment.id))
            .select_from(MessageAttachment)
            .join(EmailMessage, EmailMessage.id == MessageAttachment.message_id)
            .where(EmailMessage.thread_id == thread.id)
        )
    )

    newest_subject = await session.scalar(
        select(EmailMessage.subject)
        .where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.deleted_at.is_(None),
            EmailMessage.subject.is_not(None),
        )
        .order_by(EmailMessage.sent_at.desc())
        .limit(1)
    )

    thread.message_count = int(aggregate[0] or 0)
    thread.unread_count = int(aggregate[1] or 0)
    thread.first_message_at = aggregate[2]
    thread.latest_message_at = aggregate[3]
    thread.participant_emails = list(seen)
    thread.provider_labels = sorted({label for group in labels for label in (group or [])})
    thread.has_attachments = has_attachments
    if newest_subject:
        thread.subject = newest_subject
        from app.modules.ingest.headers import normalize_subject

        thread.subject_normalized = normalize_subject(newest_subject)

    # Every ingested message invalidates what was derived from the thread.
    thread.content_version += 1
    thread.updated_at = get_clock().now()

    await session.flush()
    await session.execute(_REFRESH_TSV, {"thread_id": str(thread.id)})


async def soft_delete_message(
    session: AsyncSession, *, account_id: UUID, provider_message_id: str
) -> UUID | None:
    """Mark a message deleted and recount its thread.

    Soft, because Gmail's delete is frequently a user's mistake and a local
    row costs less than re-syncing a mailbox to undo one.
    """
    message = await session.scalar(
        select(EmailMessage).where(
            EmailMessage.account_id == account_id,
            EmailMessage.provider_message_id == provider_message_id,
        )
    )
    if message is None or message.deleted_at is not None:
        return None

    message.deleted_at = get_clock().now()
    thread = await session.get(EmailThread, message.thread_id)
    await session.flush()
    if thread is not None:
        await recount_thread(session, thread)
    return message.thread_id


async def apply_labels(
    session: AsyncSession,
    *,
    account_id: UUID,
    provider_message_id: str,
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
) -> UUID | None:
    """Apply a Gmail label change, including the read state it implies."""
    message = await session.scalar(
        select(EmailMessage).where(
            EmailMessage.account_id == account_id,
            EmailMessage.provider_message_id == provider_message_id,
        )
    )
    if message is None:
        return None

    labels = set(message.provider_labels or [])
    labels.update(added)
    labels.difference_update(removed)
    message.provider_labels = sorted(labels)
    message.is_read = "UNREAD" not in labels

    thread = await session.get(EmailThread, message.thread_id)
    await session.flush()
    if thread is not None:
        await recount_thread(session, thread)
    return message.thread_id


async def known_message_ids(
    session: AsyncSession, *, account_id: UUID, after: object | None = None
) -> set[str]:
    """Provider ids Maail already holds, for reconciliation's set difference."""
    statement = select(EmailMessage.provider_message_id).where(
        EmailMessage.account_id == account_id, EmailMessage.deleted_at.is_(None)
    )
    if after is not None:
        statement = statement.where(EmailMessage.sent_at >= after)
    return {row for row in (await session.scalars(statement)).all()}


async def messages_needing_bodies(
    session: AsyncSession, *, account_id: UUID, limit: int, max_attempts: int = 3
) -> list[tuple[UUID, str]]:
    """Pass 2's work list: newest first, skipping what keeps failing."""
    rows = (
        await session.execute(
            select(EmailMessage.id, EmailMessage.provider_message_id)
            .where(
                EmailMessage.account_id == account_id,
                EmailMessage.body_fetched_at.is_(None),
                EmailMessage.deleted_at.is_(None),
                EmailMessage.body_fetch_attempts < max_attempts,
            )
            .order_by(EmailMessage.sent_at.desc())
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def record_body_failure(session: AsyncSession, *, message_id: UUID, reason: str) -> None:
    """One unfetchable message must not stall a mailbox (gap A7)."""
    await session.execute(
        update(EmailMessage)
        .where(EmailMessage.id == message_id)
        .values(
            body_fetch_attempts=EmailMessage.body_fetch_attempts + 1,
            last_fetch_error=reason[:500],
        )
    )


async def live_threads(session: AsyncSession, *, account_id: UUID) -> int:
    """Threads that have not been merged away. Used by the progress UI."""
    return int(
        await session.scalar(
            select(func.count(EmailThread.id)).where(
                EmailThread.account_id == account_id,
                EmailThread.merged_into_thread_id.is_(None),
                or_(EmailThread.message_count > 0, EmailThread.message_count.is_(None)),
            )
        )
        or 0
    )
