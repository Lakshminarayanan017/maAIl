"""The deterministic intent router: answer it in SQL, or admit you cannot.

This runs before the Companion agent and it is the reason the companion is
affordable. A large share of what people actually ask their mailbox is a
count or a filter over judgements that were already made and written down:

    "which emails need my attention"      priority >= 2, stored
    "what is due this week"               deadlines, stored
    "how many unread"                     count
    "what are my tasks"                   tasks, stored
    "anything from <someone>"             sender filter

None of those needs a model, and routing them to one would be paying for
inference to run a ``WHERE`` clause. Phase 10 tracks the share of turns
resolved with zero model calls; this module is that share.

It is a **matcher, not a parser**. It recognises a small set of shapes
with high confidence and returns ``None`` for everything else. A router
that tried to handle every question would start half-answering the ones
it misread, which is worse than passing them on: a wrong cheap answer
costs more trust than a right expensive one costs money.

Every answer it produces is built from rows, so the references in it are
real by construction -- there is no model in this path to invent one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["RoutedAnswer", "ThreadRef", "route_question"]


@dataclass(frozen=True)
class ThreadRef:
    """A clickable reference to a real thread."""

    thread_id: UUID
    subject: str | None
    sender: str | None
    #: What makes it relevant to the answer -- the stored reason, the due
    #: date. Never an unexplained chip.
    detail: str | None = None


@dataclass
class RoutedAnswer:
    answer: str
    #: 'sql' when computed from rows here, 'cached' when read back from
    #: stored intelligence. Both cost nothing; the distinction is kept
    #: because they are different claims about where the answer came from.
    route: str = "sql"
    references: list[ThreadRef] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)


_ATTENTION = text(
    """
    SELECT t.id, t.subject, ti.priority, ti.priority_reason,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.id AND NOT m.is_from_user AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1)
      FROM thread_intelligence ti
      JOIN email_threads t ON t.id = ti.thread_id
     WHERE ti.priority >= 2 AND t.merged_into_thread_id IS NULL
     ORDER BY ti.priority DESC, t.latest_message_at DESC NULLS LAST
     LIMIT 10
    """
)

_NEEDS_REPLY = text(
    """
    SELECT t.id, t.subject, ti.priority, ti.priority_reason,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.id AND NOT m.is_from_user AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1)
      FROM thread_intelligence ti
      JOIN email_threads t ON t.id = ti.thread_id
     WHERE ti.needs_reply AND t.merged_into_thread_id IS NULL
     ORDER BY t.latest_message_at DESC NULLS LAST
     LIMIT 10
    """
)

_COUNTS = text(
    """
    SELECT count(*), count(*) FILTER (WHERE unread_count > 0),
           count(*) FILTER (WHERE latest_message_at >= date_trunc('day', now())),
           count(ti.thread_id)
      FROM email_threads t
      LEFT JOIN thread_intelligence ti ON ti.thread_id = t.id
     WHERE t.merged_into_thread_id IS NULL
    """
)

_DEADLINES = text(
    """
    SELECT d.id, d.thread_id, t.subject, d.raw_phrase, d.normalized_date,
           d.resolution_status::text, d.message_id,
           d.evidence_char_start, d.evidence_char_end,
           (SELECT m.from_email FROM email_messages m
             WHERE m.thread_id = t.id AND NOT m.is_from_user AND m.deleted_at IS NULL
             ORDER BY m.sent_at DESC LIMIT 1)
      FROM deadlines d
      JOIN email_threads t ON t.id = d.thread_id
     WHERE d.superseded_by IS NULL AND d.is_for_user
       AND (d.normalized_date IS NULL OR d.normalized_date >= current_date)
     ORDER BY d.normalized_date NULLS LAST
     LIMIT 10
    """
)

_TASKS = text(
    """
    SELECT id, title, due_at, origin, thread_id
      FROM tasks
     WHERE status = 'pending'
     ORDER BY due_at ASC NULLS LAST
     LIMIT 15
    """
)

_FROM_SENDER = text(
    """
    SELECT t.id, t.subject, ti.priority, ti.priority_reason, m.from_email
      FROM email_threads t
      JOIN email_messages m ON m.thread_id = t.id AND NOT m.is_from_user
      LEFT JOIN thread_intelligence ti ON ti.thread_id = t.id
     WHERE t.merged_into_thread_id IS NULL
       AND m.deleted_at IS NULL
       AND (lower(m.from_email) LIKE :needle OR lower(coalesce(m.from_name, '')) LIKE :needle)
     GROUP BY t.id, t.subject, ti.priority, ti.priority_reason, m.from_email
     ORDER BY t.latest_message_at DESC NULLS LAST
     LIMIT 10
    """
)

# Patterns, most specific first. Each one is a shape someone actually
# types, not a grammar.
_ATTENTION_RE = re.compile(
    r"\b(need(s)? (my|your) attention|needs attention|what needs me|"
    r"what('?s| is) (important|urgent)|important (emails?|threads?)|"
    r"high priority|urgent (emails?|threads?))\b",
    re.I,
)
_REPLY_RE = re.compile(
    r"\b(pending repl(y|ies)|awaiting (my )?repl|need(s)? (a )?repl|"
    r"waiting on me|unanswered|haven'?t replied|yet to reply)\b",
    re.I,
)
_COUNT_RE = re.compile(
    r"\b(how many|count of|number of)\b.*\b(email|message|thread|unread)\b", re.I
)
_UNREAD_RE = re.compile(r"\b(unread)\b", re.I)
_DEADLINE_RE = re.compile(
    r"\b(deadlines?|due (date|this|next|soon|today|tomorrow)|"
    r"what('?s| is) due|when (is|are).*(due|deadline))\b",
    re.I,
)
_TASK_RE = re.compile(
    r"\b(my tasks?|pending tasks?|to-?dos?|task list|what do i (have to|need to) do)\b",
    re.I,
)
# Two shapes only, and both are narrow on purpose. The permissive
# version of this -- "from" followed by a word -- matched "from last
# month" in "summarise my technical conversations from last month" and
# answered "nothing from 'last month' in your mail", which is the
# half-answer failure this module's docstring warns about. A real
# question routed to a wrong cheap answer costs more trust than a right
# expensive one costs money.
#
# 1. An actual address, anywhere in the question.
_SENDER_ADDRESS_RE = re.compile(r"(?P<who>[\w.+-]+@[\w.-]+\.\w{2,})")
# 2. An explicitly mail-scoped phrase: "emails from X", "anything from X".
#    Bare "from X" does not qualify, because "from" is a preposition
#    before it is a filter.
_SENDER_PHRASE_RE = re.compile(
    r"\b(?:anything|everything|emails?|messages?|mail|threads?)\s+from\s+"
    r"(?P<who>[\w.+-]+(?:\s+[\w.-]+)?)",
    re.I,
)
#: Words that follow "from" and are not people. Without this, a date
#: range reads as a correspondent.
_NOT_A_SENDER = frozenset(
    {
        "last",
        "this",
        "next",
        "yesterday",
        "today",
        "tomorrow",
        "week",
        "month",
        "year",
        "now",
        "then",
        "recent",
        "recently",
        "anyone",
        "anybody",
        "everyone",
        "me",
        "my",
        "work",
        "my inbox",
        "the inbox",
        "inbox",
    }
)


async def route_question(session: AsyncSession, question: str) -> RoutedAnswer | None:
    """Answer deterministically, or return None to pass it to the agent."""
    asked = question.strip()
    if not asked:
        return None

    if _ATTENTION_RE.search(asked):
        return await _threads_answer(
            session,
            _ATTENTION,
            empty="Nothing is marked as needing your attention right now.",
            lead="{n} thread{s} marked as needing attention",
            follow_ups=["Summarise the first one", "What is due this week?"],
        )

    if _REPLY_RE.search(asked):
        return await _threads_answer(
            session,
            _NEEDS_REPLY,
            empty="Nothing is waiting on a reply from you.",
            lead="{n} thread{s} waiting on a reply from you",
            follow_ups=["Draft a reply to the first one"],
        )

    if _DEADLINE_RE.search(asked):
        return await _deadlines_answer(session)

    if _TASK_RE.search(asked):
        return await _tasks_answer(session)

    if _COUNT_RE.search(asked) or (_UNREAD_RE.search(asked) and len(asked) < 40):
        row = (await session.execute(_COUNTS)).one()
        total, unread, today, analysed = (int(value or 0) for value in row)
        return RoutedAnswer(
            answer=(
                f"{total} thread{'s' if total != 1 else ''} in total, "
                f"{unread} unread, {today} from today. "
                f"{analysed} {'has' if analysed == 1 else 'have'} been analysed."
            ),
            follow_ups=["Which need my attention?"] if unread else [],
        )

    who = _sender_in(asked)
    if who is not None:
        rows = (await session.execute(_FROM_SENDER, {"needle": f"%{who.lower()}%"})).all()
        if rows:
            refs = [_ref(row) for row in rows]
            return RoutedAnswer(
                answer=(f"{len(refs)} thread{'s' if len(refs) != 1 else ''} matching “{who}”."),
                references=refs,
            )
        # No rows is not "I cannot answer": it is an answer, and a
        # useful one. Passing it to a model would spend money to say
        # the same thing less precisely.
        return RoutedAnswer(answer=f"Nothing from “{who}” in your mail.")

    return None


def _sender_in(asked: str) -> str | None:
    """The correspondent this question is about, if it names one at all.

    Returns None rather than guessing. An address counts anywhere; a bare
    name counts only after a mail-scoped phrase, and never when it is a
    time word.
    """
    address = _SENDER_ADDRESS_RE.search(asked)
    if address:
        return address.group("who").strip()

    phrase = _SENDER_PHRASE_RE.search(asked)
    if phrase is None:
        return None

    who = phrase.group("who").strip()
    first = who.split()[0].lower() if who.split() else ""
    # Two characters is not a name, and a date is not a person.
    if len(who) < 3 or first in _NOT_A_SENDER:
        return None
    return who


async def _threads_answer(
    session: AsyncSession,
    query: Any,
    *,
    empty: str,
    lead: str,
    follow_ups: list[str],
) -> RoutedAnswer:
    rows = (await session.execute(query)).all()
    if not rows:
        return RoutedAnswer(answer=empty, route="cached")

    refs = [_ref(row) for row in rows]
    return RoutedAnswer(
        answer=lead.format(n=len(refs), s="s" if len(refs) != 1 else ""),
        # Read back from stored judgements rather than computed here, and
        # labelled as such.
        route="cached",
        references=refs,
        follow_ups=follow_ups,
    )


async def _deadlines_answer(session: AsyncSession) -> RoutedAnswer:
    rows = (await session.execute(_DEADLINES)).all()
    if not rows:
        return RoutedAnswer(
            answer="No deadlines are recorded for you.",
            route="cached",
            follow_ups=["Which emails need my attention?"],
        )

    refs: list[ThreadRef] = []
    citations: list[dict[str, Any]] = []
    unclear = 0

    for row in rows:
        status = str(row[5])
        if status == "ambiguous":
            unclear += 1
            # An ambiguous deadline is quoted, never dated. The chip says
            # the sender's words and that the day is unclear.
            detail = f"“{row[3]}” — which day is unclear"
        elif row[4] is None:
            detail = f"“{row[3]}” — no date named"
        else:
            detail = f"{row[4].isoformat()} (“{row[3]}”)"

        refs.append(ThreadRef(thread_id=row[1], subject=row[2], sender=row[9], detail=detail))
        if row[6] is not None and row[7] is not None:
            citations.append(
                {
                    "thread_id": str(row[1]),
                    "message_id": str(row[6]),
                    "char_start": int(row[7]),
                    "char_end": int(row[8]),
                }
            )

    dated = len(refs) - unclear
    parts = [f"{dated} deadline{'s' if dated != 1 else ''} with a date"]
    if unclear:
        parts.append(f"{unclear} where the day is unclear and needs you to say which")

    return RoutedAnswer(
        answer=" · ".join(parts) + ".",
        route="cached",
        references=refs,
        citations=citations,
        follow_ups=["Resolve the unclear ones"] if unclear else [],
    )


async def _tasks_answer(session: AsyncSession) -> RoutedAnswer:
    rows = (await session.execute(_TASKS)).all()
    if not rows:
        return RoutedAnswer(answer="You have no pending tasks.", route="cached")

    lines = []
    refs: list[ThreadRef] = []
    for row in rows:
        due = row[2].date().isoformat() if row[2] else "no date"
        lines.append(f"— {row[1]} ({due})")
        if row[4] is not None:
            refs.append(ThreadRef(thread_id=row[4], subject=row[1], sender=None, detail=due))

    return RoutedAnswer(
        answer=f"{len(rows)} pending task{'s' if len(rows) != 1 else ''}.\n" + "\n".join(lines),
        route="cached",
        references=refs,
    )


def _ref(row: object) -> ThreadRef:
    data: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
    reason = data[3]
    priority = data[2]
    detail = str(reason) if reason else (f"priority {priority}" if priority else None)
    return ThreadRef(thread_id=data[0], subject=data[1], sender=data[4], detail=detail)
