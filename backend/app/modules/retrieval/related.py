"""Related context: other threads that touch the same thing. No model.

Section five of the intelligence panel, and it costs nothing. The query is
the thread's own distinctive terms against the search vector every thread
already maintains, which means related context is always current -- a new
message changes the answer on the next read, with nothing to invalidate.

That is why it deliberately gets **no table**. A stored "related threads"
list would be a second copy that goes stale every time mail arrives, and
would need an invalidation rule for every write path. Recomputing a
ranked query is cheaper than being wrong.

The terms come from Postgres, not from a model: ``ts_stat`` style term
extraction over the thread's own tsvector gives the words that are
distinctive *in this thread*, and stop words are already gone because the
vector was built with the English configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["RelatedThread", "find_related"]

MAX_RELATED = 6
#: Terms to build the query from. More than this and the query matches
#: everything, which is the same as matching nothing.
MAX_TERMS = 6
#: Below this length a lexeme is noise even after stop-word removal.
MIN_TERM = 4

_TERMS = text(
    """
    SELECT word FROM (
      SELECT unnest(string_to_array(
               regexp_replace(t.search_tsv::text, E'\\\\:[0-9A-D,]*', '', 'g'),
               ' '
             )) AS word
        FROM email_threads t
       WHERE t.id = :thread_id
    ) AS words
     WHERE length(word) >= :min_term
     LIMIT 200
    """
)

_RELATED = text(
    """
    SELECT t.id, t.subject, t.latest_message_at, t.message_count,
           ti.category::text, ti.priority,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.id AND NOT m.is_from_user AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1),
           ts_rank(t.search_tsv, websearch_to_tsquery('english', :q)) AS rank
      FROM email_threads t
      LEFT JOIN thread_intelligence ti ON ti.thread_id = t.id
     WHERE t.id <> :thread_id
       AND t.merged_into_thread_id IS NULL
       AND t.search_tsv @@ websearch_to_tsquery('english', :q)
     ORDER BY rank DESC, t.latest_message_at DESC NULLS LAST
     LIMIT :limit
    """
)

_PARTICIPANT_THREADS = text(
    """
    SELECT t.id, t.subject, t.latest_message_at, t.message_count,
           ti.category::text, ti.priority, m.from_email, 0.0 AS rank
      FROM email_threads t
      JOIN email_messages m ON m.thread_id = t.id AND NOT m.is_from_user
      LEFT JOIN thread_intelligence ti ON ti.thread_id = t.id
     WHERE t.id <> :thread_id
       AND t.merged_into_thread_id IS NULL
       AND m.deleted_at IS NULL
       AND lower(m.from_email) = lower(:sender)
     GROUP BY t.id, t.subject, t.latest_message_at, t.message_count,
              ti.category, ti.priority, m.from_email
     ORDER BY t.latest_message_at DESC NULLS LAST
     LIMIT :limit
    """
)

_CLEAN = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class RelatedThread:
    thread_id: UUID
    subject: str | None
    sender: str | None
    latest_message_at: datetime | None
    message_count: int
    category: str | None
    priority: int | None
    #: Why this thread is here, shown to the reader. "Also from this
    #: sender" and "mentions deployment, staging" are different claims and
    #: the panel says which.
    because: str


async def find_related(
    session: AsyncSession,
    *,
    thread_id: UUID,
    sender: str | None = None,
    limit: int = MAX_RELATED,
) -> list[RelatedThread]:
    """Threads related to this one, by shared terms and by sender.

    Two passes rather than one ranked query, because "the same person
    wrote to you about something else" and "another thread mentions the
    same repository" are different kinds of relatedness and collapsing
    them into one score makes the reason unsayable.
    """
    found: dict[UUID, RelatedThread] = {}

    raw_terms = [
        str(row[0]).strip("'")
        for row in (
            await session.execute(_TERMS, {"thread_id": str(thread_id), "min_term": MIN_TERM})
        ).all()
    ]
    terms: list[str] = []
    for term in raw_terms:
        cleaned = _CLEAN.sub("", term.lower())
        if len(cleaned) >= MIN_TERM and cleaned not in terms:
            terms.append(cleaned)
        if len(terms) >= MAX_TERMS:
            break

    if terms:
        query = " or ".join(terms)
        rows = (
            await session.execute(
                _RELATED, {"thread_id": str(thread_id), "q": query, "limit": limit}
            )
        ).all()
        for row in rows:
            found[row[0]] = _row_to_related(row, because=f"Mentions {', '.join(terms[:3])}")

    if sender and len(found) < limit:
        rows = (
            await session.execute(
                _PARTICIPANT_THREADS,
                {"thread_id": str(thread_id), "sender": sender, "limit": limit},
            )
        ).all()
        for row in rows:
            if row[0] in found or len(found) >= limit:
                continue
            found[row[0]] = _row_to_related(row, because=f"Also from {sender}")

    return list(found.values())[:limit]


def _row_to_related(row: object, *, because: str) -> RelatedThread:
    data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
    return RelatedThread(
        thread_id=data[0],
        subject=data[1],
        latest_message_at=data[2],
        message_count=int(data[3] or 0),
        category=data[4],
        priority=int(data[5]) if data[5] is not None else None,
        sender=data[6],
        because=because,
    )
