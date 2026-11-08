"""MCP server: mail. Read-only, Plane U.

Every tool here can be given to an agent that has just read a hostile
email, which is why not one of them can send, label, delete or reach the
network. The plane is not a label on a dangerous tool; it is the reason
these tools were written this way.

Text comes back **stripped**: quoted history is the single largest token
cost in the system, and an agent that asks for a thread should not pay for
nine copies of message one.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from app.core.tenancy import tenant_session
from app.database.models.thread import EmailMessage, EmailThread
from app.modules.mcp.catalog import Capability, Plane, ToolSpec
from app.modules.mcp.transports.inprocess import InProcessServer

server = InProcessServer(name="mail")

READ_ONLY = frozenset({Capability.read})

#: Caps that exist so one tool call cannot become the whole mailbox.
MAX_MESSAGES = 50
MAX_THREADS = 25
MAX_CHARS = 4000


@server.tool(
    ToolSpec(
        name="mail.get_thread",
        server="mail",
        description=(
            "Read one email thread: its subject, participants and messages, with "
            "quoted history removed. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "format": "uuid"},
                "thread_id": {"type": "string", "format": "uuid"},
                "max_messages": {"type": "integer", "minimum": 1, "maximum": MAX_MESSAGES},
            },
            "required": ["user_id", "thread_id"],
            "additionalProperties": False,
        },
        plane=Plane.U,
        capabilities=READ_ONLY,
    )
)
async def get_thread(args: dict[str, Any]) -> dict[str, Any]:
    user_id = UUID(str(args["user_id"]))
    thread_id = UUID(str(args["thread_id"]))
    limit = min(int(args.get("max_messages", 20)), MAX_MESSAGES)

    async with tenant_session(user_id) as session:
        thread = await session.get(EmailThread, thread_id)
        if thread is None:
            # RLS already filtered another tenant's row out, so "not yours"
            # and "does not exist" arrive here identically, and the tool
            # answers the same way for both.
            return {"found": False}

        messages = (
            await session.scalars(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread_id, EmailMessage.deleted_at.is_(None))
                .order_by(EmailMessage.sent_at.desc())
                .limit(limit)
            )
        ).all()

        return {
            "found": True,
            "thread_id": str(thread.id),
            "subject": thread.subject,
            "participants": list(thread.participant_emails),
            "message_count": thread.message_count,
            "content_version": thread.content_version,
            "messages": [
                {
                    "message_id": str(message.id),
                    "from": message.from_email,
                    "sent_at": message.sent_at.isoformat(),
                    "is_from_user": message.is_from_user,
                    "text": (message.body_text_stripped or message.snippet or "")[:MAX_CHARS],
                }
                for message in reversed(list(messages))
            ],
        }


@server.tool(
    ToolSpec(
        name="mail.list_recent_threads",
        server="mail",
        description=(
            "List the most recent email threads for a user, newest first. Subjects "
            "and senders only, no bodies. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "format": "uuid"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_THREADS},
            },
            "required": ["user_id"],
            "additionalProperties": False,
        },
        plane=Plane.U,
        capabilities=READ_ONLY,
    )
)
async def list_recent_threads(args: dict[str, Any]) -> dict[str, Any]:
    user_id = UUID(str(args["user_id"]))
    limit = min(int(args.get("limit", 10)), MAX_THREADS)

    async with tenant_session(user_id) as session:
        threads = (
            await session.scalars(
                select(EmailThread)
                .where(
                    EmailThread.merged_into_thread_id.is_(None),
                    EmailThread.message_count > 0,
                )
                .order_by(EmailThread.latest_message_at.desc().nullslast())
                .limit(limit)
            )
        ).all()

        return {
            "threads": [
                {
                    "thread_id": str(thread.id),
                    "subject": thread.subject,
                    "participants": list(thread.participant_emails)[:5],
                    "message_count": thread.message_count,
                    "unread_count": thread.unread_count,
                    "latest_message_at": (
                        thread.latest_message_at.isoformat() if thread.latest_message_at else None
                    ),
                }
                for thread in threads
            ]
        }


@server.tool(
    ToolSpec(
        name="mail.get_sender_history",
        server="mail",
        description=(
            "How much the user has corresponded with an address: how many threads, "
            "how many the user replied to, and when they last did. Counts only, no "
            "message content. Read-only."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "format": "uuid"},
                "email": {"type": "string", "maxLength": 320},
            },
            "required": ["user_id", "email"],
            "additionalProperties": False,
        },
        plane=Plane.U,
        capabilities=READ_ONLY,
    )
)
async def get_sender_history(args: dict[str, Any]) -> dict[str, Any]:
    """Whether this is someone the user actually talks to.

    The single most useful signal Triage has, and it costs a query rather
    than a judgement: an unfamiliar sender is not automatically unimportant,
    but a sender the user has replied to eleven times is rarely noise.
    """
    user_id = UUID(str(args["user_id"]))
    email = str(args["email"]).strip().lower()[:320]

    async with tenant_session(user_id) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                      count(DISTINCT m.thread_id) AS threads,
                      count(DISTINCT m.thread_id) FILTER (
                        WHERE EXISTS (
                          SELECT 1 FROM email_messages r
                          WHERE r.thread_id = m.thread_id AND r.is_from_user
                        )
                      ) AS replied_threads,
                      max(m.sent_at) AS last_seen
                    FROM email_messages m
                    WHERE m.from_email = :email AND m.deleted_at IS NULL
                    """
                ),
                {"email": email},
            )
        ).one()

    threads = int(row[0] or 0)
    replied = int(row[1] or 0)
    return {
        "email": email,
        "known": threads > 0,
        "thread_count": threads,
        "replied_thread_count": replied,
        "last_seen_at": row[2].isoformat() if row[2] else None,
        # A plain ratio, not a score. The agent reads the numbers.
        "reply_rate": round(replied / threads, 2) if threads else 0.0,
    }
