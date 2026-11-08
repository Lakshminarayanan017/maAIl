"""The inbox list and one thread. Cursor-paginated. Zero LLM.

The cursor encodes ``(latest_message_at, id)``, which is also the index, so
a page is an index range scan rather than an OFFSET. OFFSET pagination
re-reads and discards every row before the page, which is survivable at page
2 and not at page 200 — and it silently duplicates or skips rows when mail
arrives mid-scroll, which is exactly when someone is paging.

Filters that depend on classification are not here. They arrive with the
Triage agent in phase 6. A filter that returned an empty list today would
read as "you have no technical email", which is a lie told by omission.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, func, literal, or_, select, text
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.database.models.account import ConnectedAccount
from app.database.models.intelligence import ThreadIntelligence, UserOverride
from app.database.models.thread import EmailMessage, EmailThread
from app.modules.accounts import service as account_service
from app.modules.ingest.date_parser import find_date_candidates
from app.modules.ingest.sanitizer import sanitize_email_html
from app.modules.providers.email.base import MessageUnavailable, ProviderError
from app.modules.providers.email.gmail import GmailClient
from app.modules.providers.oauth.base import ReauthRequired
from app.modules.providers.oauth.google import GoogleOAuthClient

router = APIRouter(tags=["threads"])
log = get_logger(__name__)

MAX_LIMIT = 100
DEFAULT_LIMIT = 50

#: Only what phase 2 can answer honestly. The rest land with classification.
ThreadFilter = Literal[
    "all",
    "unread",
    "archived",
    "important",
    "technical",
    "opportunities",
    "team",
    "notifications",
]


class Participant(BaseModel):
    email: str | None
    name: str | None


class ThreadListItem(BaseModel):
    id: UUID
    subject: str | None
    #: Whoever the thread is "from" in the list: the newest sender who is
    #: not the account owner, so a conversation does not show your own name.
    sender: Participant
    preview: str | None
    latest_message_at: datetime | None
    message_count: int
    unread_count: int
    has_attachments: bool
    is_read: bool
    content_version: int

    # --- AI-derived, and labelled as such ------------------------------
    #: Null until Triage has run. The row renders "not analysed" rather
    #: than leaving a gap that later shifts the layout.
    category: str | None = None
    priority: int | None = None
    #: Never an unexplained badge. Shown on hover next to the priority.
    priority_reason: str | None = None
    needs_reply: bool | None = None
    is_technical: bool | None = None
    #: Which decided it: a rule you wrote, a correction you made, or an
    #: agent. The three must stay distinguishable on screen.
    category_source: str | None = None
    #: Per capability, never one global boolean.
    status_summary: str = "pending"
    status_deadline: str = "pending"
    status_actions: str = "pending"
    #: True when the stored intelligence predates the newest message.
    stale: bool = False


class ThreadPage(BaseModel):
    items: list[ThreadListItem]
    next_cursor: str | None
    #: Null while a sync is still running: a count that keeps changing is
    #: worse than no count.
    total: int | None = None


class MessageOut(BaseModel):
    id: UUID
    from_email: str | None
    from_name: str | None
    to_emails: list[str]
    cc_emails: list[str]
    subject: str | None
    sent_at: datetime
    snippet: str | None
    body_text: str | None
    is_from_user: bool
    is_read: bool
    has_body: bool
    #: Quoted history and signature removed. What every agent will read.
    body_text_stripped: str | None = None
    #: How much the stripper removed. Surfaced so the saving is visible
    #: rather than merely claimed.
    stripped_ratio: float | None = None
    date_candidates: list[DateCandidateOut] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)


class AttachmentOut(BaseModel):
    id: UUID
    filename: str | None
    mime_type: str | None
    size_bytes: int | None


class ThreadDetail(BaseModel):
    id: UUID
    subject: str | None
    participants: list[str]
    message_count: int
    unread_count: int
    has_attachments: bool
    first_message_at: datetime | None
    latest_message_at: datetime | None
    content_version: int
    messages: list[MessageOut]


class ReadState(BaseModel):
    is_read: bool


class LinkWarningOut(BaseModel):
    text: str
    href: str
    claimed_host: str
    actual_host: str


class MessageBody(BaseModel):
    """Sanitised HTML, fetched on demand and never stored (gap E6)."""

    message_id: UUID
    html: str
    #: Remote images withheld until the reader asks. A tracking pixel is a
    #: read receipt the sender did not ask permission for.
    blocked_images: int
    images_loaded: bool
    #: Anchors whose visible text names a different host than the href.
    link_warnings: list[LinkWarningOut]
    empty: bool


class DateCandidateOut(BaseModel):
    """A date-ish phrase, where it was, and what it resolves to.

    Deterministic: this is text that is in the message, not an inference
    about it. The Deadline agent in phase 9 decides which of these are
    deadlines, for whom, and whether they matter.
    """

    text: str
    start: int
    end: int
    kind: str
    resolved: str | None
    confidence_band: str
    rule: str


# ---------------------------------------------------------------------------
# cursor
# ---------------------------------------------------------------------------
def encode_cursor(moment: datetime | None, thread_id: UUID) -> str:
    stamp = moment.isoformat() if moment else ""
    return base64.urlsafe_b64encode(f"{stamp}|{thread_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime | None, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, _, identifier = raw.partition("|")
        return (datetime.fromisoformat(stamp) if stamp else None), UUID(identifier)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That page cursor is not valid") from exc


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
#: Filters that read stored intelligence. No model runs to answer one.
INTELLIGENCE_FILTERS: dict[str, str] = {
    "important": "priority >= 2",
    "technical": "is_technical",
    "opportunities": "category = 'opportunity'",
    "team": "category IN ('personal', 'administrative')",
    "notifications": "category IN ('notification', 'promotional')",
}


def _base_query() -> Select[tuple[EmailThread]]:
    return select(EmailThread).where(
        # A merged thread is an artefact of Gmail changing its mind. The
        # survivor carries its messages, so listing both would show the
        # same conversation twice.
        EmailThread.merged_into_thread_id.is_(None),
        EmailThread.message_count > 0,
    )


def _has_label(label: str) -> ColumnElement[bool]:
    """`label = ANY(provider_labels)`, which the GIN index can answer."""
    return literal(label).op("=")(func.any(EmailThread.provider_labels))


def _apply_filter(
    statement: Select[tuple[EmailThread]], which: ThreadFilter
) -> Select[tuple[EmailThread]]:
    if which == "unread":
        return statement.where(_has_label("INBOX"), EmailThread.unread_count > 0)
    if which == "archived":
        # Archived in Gmail means: the message exists but is not in INBOX.
        return statement.where(~_has_label("INBOX"))

    clause = INTELLIGENCE_FILTERS.get(which)
    if clause:
        # Reads the stored judgement. Zero model calls to filter an inbox.
        return statement.where(
            _has_label("INBOX"),
            EmailThread.id.in_(select(ThreadIntelligence.thread_id).where(text(clause))),
        )
    return statement.where(_has_label("INBOX"))


@router.get("/threads", response_model=ThreadPage, summary="The inbox, one page at a time")
async def list_threads(
    auth: AuthContext,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    thread_filter: Annotated[ThreadFilter, Query(alias="filter")] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ThreadPage:
    statement = _apply_filter(_base_query(), thread_filter)

    if q:
        # Postgres full-text search, which is what replaces a vector store
        # in v1. `websearch_to_tsquery` takes what a person actually types.
        statement = statement.where(
            EmailThread.search_tsv.op("@@")(func.websearch_to_tsquery("english", q))
        )

    if cursor:
        moment, last_id = decode_cursor(cursor)
        if moment is not None:
            statement = statement.where(
                or_(
                    EmailThread.latest_message_at < moment,
                    and_(
                        EmailThread.latest_message_at == moment,
                        EmailThread.id < last_id,
                    ),
                )
            )

    statement = statement.order_by(
        EmailThread.latest_message_at.desc().nullslast(), EmailThread.id.desc()
    ).limit(limit + 1)

    threads = list((await auth.session.scalars(statement)).all())
    has_more = len(threads) > limit
    threads = threads[:limit]

    items = [await _to_list_item(auth, thread) for thread in threads]
    next_cursor = encode_cursor(threads[-1].latest_message_at, threads[-1].id) if has_more else None
    return ThreadPage(items=items, next_cursor=next_cursor)


async def _to_list_item(auth: AuthContext, thread: EmailThread) -> ThreadListItem:
    intelligence = await auth.session.get(ThreadIntelligence, thread.id)

    newest = (
        await auth.session.execute(
            select(
                EmailMessage.from_email,
                EmailMessage.from_name,
                EmailMessage.snippet,
                EmailMessage.body_text,
                EmailMessage.is_from_user,
            )
            .where(EmailMessage.thread_id == thread.id, EmailMessage.deleted_at.is_(None))
            .order_by(EmailMessage.is_from_user.asc(), EmailMessage.sent_at.desc())
            .limit(1)
        )
    ).first()

    from_email = newest[0] if newest else None
    from_name = newest[1] if newest else None
    snippet = (newest[2] if newest else None) or None
    if not snippet and newest and newest[3]:
        snippet = " ".join(str(newest[3]).split())[:200]

    return ThreadListItem(
        id=thread.id,
        subject=thread.subject,
        sender=Participant(email=from_email, name=from_name),
        preview=snippet,
        latest_message_at=thread.latest_message_at,
        message_count=thread.message_count,
        unread_count=thread.unread_count,
        has_attachments=thread.has_attachments,
        is_read=thread.unread_count == 0,
        content_version=thread.content_version,
        category=intelligence.category if intelligence else None,
        priority=intelligence.priority if intelligence else None,
        priority_reason=intelligence.priority_reason if intelligence else None,
        needs_reply=intelligence.needs_reply if intelligence else None,
        is_technical=intelligence.is_technical if intelligence else None,
        category_source=intelligence.category_source if intelligence else None,
        status_summary=intelligence.status_summary if intelligence else "pending",
        status_deadline=intelligence.status_deadline if intelligence else "pending",
        status_actions=intelligence.status_actions if intelligence else "pending",
        # A judgement made from an older version of the thread is still a
        # judgement, and it is shown -- labelled, not hidden.
        stale=bool(
            intelligence and intelligence.computed_from_content_version < thread.content_version
        ),
    )


@router.get(
    "/threads/{thread_id}", response_model=ThreadDetail, summary="One thread and its messages"
)
async def read_thread(thread_id: UUID, auth: AuthContext) -> ThreadDetail:
    # Relative phrases resolve in the reader's timezone, not the server's
    # (gap E2). One lookup for the whole thread.
    timezone_name = (
        await auth.session.scalar(
            text("SELECT timezone FROM users WHERE id = :id"), {"id": str(auth.user_id)}
        )
    ) or "UTC"

    thread = await auth.session.get(EmailThread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such thread")

    if thread.merged_into_thread_id is not None:
        # Follow the merge rather than showing an empty husk: a bookmark to
        # a thread Gmail later merged should still open the conversation.
        survivor = await auth.session.get(EmailThread, thread.merged_into_thread_id)
        if survivor is not None:
            thread = survivor

    messages = (
        await auth.session.scalars(
            select(EmailMessage)
            .where(EmailMessage.thread_id == thread.id, EmailMessage.deleted_at.is_(None))
            .order_by(EmailMessage.sent_at)
        )
    ).all()

    return ThreadDetail(
        id=thread.id,
        subject=thread.subject,
        participants=list(thread.participant_emails),
        message_count=thread.message_count,
        unread_count=thread.unread_count,
        has_attachments=thread.has_attachments,
        first_message_at=thread.first_message_at,
        latest_message_at=thread.latest_message_at,
        content_version=thread.content_version,
        messages=[
            MessageOut(
                id=message.id,
                from_email=message.from_email,
                from_name=message.from_name,
                to_emails=list(message.to_emails),
                cc_emails=list(message.cc_emails),
                subject=message.subject,
                sent_at=message.sent_at,
                snippet=message.snippet,
                body_text=message.body_text,
                is_from_user=message.is_from_user,
                is_read=message.is_read,
                has_body=message.body_fetched_at is not None,
                body_text_stripped=message.body_text_stripped,
                stripped_ratio=message.stripped_ratio,
                date_candidates=_candidates_for(message, timezone_name),
                attachments=[
                    AttachmentOut(
                        id=attachment.id,
                        filename=attachment.filename,
                        mime_type=attachment.mime_type,
                        size_bytes=attachment.size_bytes,
                    )
                    for attachment in message.attachments
                ],
            )
            for message in messages
        ],
    )


@router.post(
    "/threads/{thread_id}/read",
    response_model=ReadState,
    dependencies=[Depends(require_csrf)],
    summary="Mark a thread read or unread, locally",
)
async def set_read(thread_id: UUID, body: ReadState, auth: AuthContext) -> ReadState:
    """Local only in phase 2.

    Writing the read state back to Gmail needs the `gmail.modify` scope,
    which v1 does not hold and which screen 02 promised not to ask for. So
    this is a local state that the next delta sync reconciles against
    Gmail's, and Gmail wins — a lie that corrects itself beats a lie that
    does not.
    """
    thread = await auth.session.get(EmailThread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such thread")

    from sqlalchemy import update

    await auth.session.execute(
        update(EmailMessage)
        .where(EmailMessage.thread_id == thread.id, EmailMessage.deleted_at.is_(None))
        .values(is_read=body.is_read)
    )
    thread.unread_count = 0 if body.is_read else thread.message_count
    return ReadState(is_read=body.is_read)


def _candidates_for(message: EmailMessage, timezone_name: str) -> list[DateCandidateOut]:
    """Date candidates from the stripped text.

    Stripped, not raw: a quoted chain repeats last week's deadlines, and
    re-extracting them every time would turn one date into five.
    """
    source = message.body_text_stripped
    if not source:
        return []
    return [
        DateCandidateOut(
            text=candidate.text,
            start=candidate.start,
            end=candidate.end,
            kind=candidate.kind.value,
            resolved=candidate.resolved.isoformat() if candidate.resolved else None,
            confidence_band=candidate.confidence_band,
            rule=candidate.rule,
        )
        for candidate in find_date_candidates(
            source, sent_at=message.sent_at, user_timezone=timezone_name
        )
    ]


@router.get(
    "/threads/{thread_id}/messages/{message_id}/body",
    response_model=MessageBody,
    summary="Sanitised HTML for one message, fetched on demand",
)
async def read_body(
    thread_id: UUID,
    message_id: UUID,
    auth: AuthContext,
    images: Annotated[Literal["blocked", "allowed"], Query()] = "blocked",
) -> MessageBody:
    """Raw HTML is never stored, so it is fetched when someone looks at it.

    That costs one Gmail call per body view, which is the trade gap E6
    makes on purpose: the largest single item in the database and the
    largest single item in the breach surface, removed from both.
    """
    message = await auth.session.get(EmailMessage, message_id)
    if message is None or message.thread_id != thread_id or message.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such message")

    account = await auth.session.get(ConnectedAccount, message.account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")

    try:
        token = await account_service.ensure_access_token(
            auth.session, account=account, client=GoogleOAuthClient()
        )
    except ReauthRequired as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That account needs reconnecting before its messages can be read.",
        ) from exc

    client = GmailClient(account_id=account.id, access_token=token)
    try:
        raw = await client.get_full(message.provider_message_id)
    except MessageUnavailable as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gmail no longer has that message.") from exc
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Gmail: {exc}") from exc

    source = raw.body_html
    if not source and raw.body_text:
        # A plain-text message still goes through the same path, wrapped,
        # so the reader has one rendering surface rather than two.
        source = "<pre>" + _escape_text(raw.body_text) + "</pre>"

    clean = sanitize_email_html(source, load_images=images == "allowed")

    return MessageBody(
        message_id=message.id,
        html=clean.html,
        blocked_images=clean.blocked_images,
        images_loaded=clean.images_loaded,
        link_warnings=[
            LinkWarningOut(
                text=warning.text,
                href=warning.href,
                claimed_host=warning.claimed_host,
                actual_host=warning.actual_host,
            )
            for warning in clean.link_warnings
        ],
        empty=clean.empty,
    )


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class OverrideRequest(BaseModel):
    field: Literal["category", "priority", "needs_reply"]
    value: str | int | bool


class OverrideResponse(BaseModel):
    thread_id: UUID
    field: str
    value: str | int | bool
    #: A rule the user could create so they never have to correct this
    #: sender again. Offered, never applied.
    suggested_rule: dict[str, Any] | None = None


@router.post(
    "/threads/{thread_id}/override",
    response_model=OverrideResponse,
    dependencies=[Depends(require_csrf)],
    summary="Correct a classification",
)
async def override_classification(
    thread_id: UUID, body: OverrideRequest, auth: AuthContext
) -> OverrideResponse:
    """A correction, recorded and applied.

    > The user should be able to correct an incorrect classification.
    > These corrections can improve future personalization.
    > (08-ui-spec.md, screen 04)

    The correction wins immediately and is marked `user_override`, so the
    interface can show that a person decided this rather than a model. It
    is also kept in `user_overrides`, which is what makes the rule
    suggestion possible: "you have moved three from this sender" is only
    answerable if the three were written down.
    """
    thread = await auth.session.get(EmailThread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such thread")

    intelligence = await auth.session.get(ThreadIntelligence, thread_id)
    old = getattr(intelligence, body.field, None) if intelligence is not None else None

    if intelligence is None:
        await auth.session.execute(
            text(
                """
                INSERT INTO thread_intelligence
                    (thread_id, user_id, computed_from_content_version, pipeline_version)
                VALUES (:thread_id, :user_id, :version, 'user_override')
                ON CONFLICT (thread_id) DO NOTHING
                """
            ),
            {
                "thread_id": str(thread_id),
                "user_id": str(auth.user_id),
                "version": thread.content_version,
            },
        )
        intelligence = await auth.session.get(ThreadIntelligence, thread_id)

    assert intelligence is not None
    if body.field == "category":
        intelligence.category = str(body.value)
        intelligence.category_source = "user_override"
    elif body.field == "priority":
        intelligence.priority = max(0, min(3, int(body.value)))
        intelligence.priority_reason = "You set this"
    else:
        intelligence.needs_reply = bool(body.value)

    auth.session.add(
        UserOverride(
            user_id=auth.user_id,
            thread_id=thread_id,
            field=body.field,
            old_value={"value": old} if old is not None else None,
            new_value={"value": body.value},
        )
    )

    return OverrideResponse(
        thread_id=thread_id,
        field=body.field,
        value=body.value,
        suggested_rule=await _suggest_rule(auth, thread_id, body),
    )


async def _suggest_rule(
    auth: AuthContext, thread_id: UUID, body: OverrideRequest
) -> dict[str, Any] | None:
    """Offer a rule once the same correction has happened before.

    Twice is a pattern; once is a Tuesday. Suggesting after a single
    correction would train people to dismiss the suggestion.
    """
    if body.field != "category":
        return None

    sender = await auth.session.scalar(
        select(EmailMessage.from_email)
        .where(EmailMessage.thread_id == thread_id, EmailMessage.is_from_user.is_(False))
        .order_by(EmailMessage.sent_at.desc())
        .limit(1)
    )
    if not sender:
        return None

    same = await auth.session.scalar(
        text(
            """
            SELECT count(*) FROM user_overrides o
            JOIN email_messages m ON m.thread_id = o.thread_id
            WHERE o.field = 'category'
              AND o.new_value->>'value' = :value
              AND m.from_email = :sender
            """
        ),
        {"value": str(body.value), "sender": sender},
    )
    if int(same or 0) < 2:
        return None

    return {
        "name": f"{sender} is {body.value}",
        "match": {"from_email": sender},
        "action": {"set_category": str(body.value)},
        "because": f"You have filed {int(same or 0)} threads from {sender} as {body.value}.",
    }
