"""Check that a claim's evidence points at real words. Drop it if not.

This is the component phase 8's blocking gate rests on:

> Every AI value resolves to a real evidence span. A value with no evidence
> renders as "not determined", never as a bare value.
> (09-execution-plan.md, phase 8)

That cannot be enforced in the interface, because by the time a value
reaches the interface the question "is this span real?" needs the message
text, and the interface does not have it. So it is enforced here, between
the agent and the database: a span that does not resolve never becomes a
stored claim, and a claim that needed one and has none is stored with its
evidence empty, which is what makes the panel say "not determined".

Three things can be wrong with a span, and all three are common:

**The message id is not in this thread.** A model listing ids it saw
earlier in the conversation, or inventing a plausible uuid.

**The offsets are out of range.** Off-by-a-paragraph, or offsets into the
whole rendered prompt rather than into one message's body.

**The offsets resolve to nothing meaningful** — whitespace, or an empty
slice where ``char_start >= char_end``. Technically in range, useless as a
quotation.

A resolved span comes back with the quote attached, so everything
downstream shows the words rather than two integers. If the words cannot
be produced, there was no evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.thread import EmailMessage

log = get_logger(__name__)

__all__ = [
    "ResolvedSpan",
    "SpanResolver",
    "load_resolver",
    "load_resolver_for_messages",
]

#: Longer than this and the quote stops being a quote. The panel shows it
#: in a side pane, not a document viewer.
MAX_QUOTE_CHARS = 400
#: Shorter than this and it cannot be read as a quotation. Two characters
#: of a word prove nothing about the claim they are supposed to support.
MIN_QUOTE_CHARS = 3


@dataclass(frozen=True)
class ResolvedSpan:
    message_id: UUID
    char_start: int
    char_end: int
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": str(self.message_id),
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote": self.quote,
        }


class SpanResolver:
    """Holds one thread's message text and answers "do these offsets exist".

    Built once per run from the same text the agent was given. Resolving
    against anything else -- the raw body, the rendered prompt, a newer
    version of the message -- would make a span that was correct when the
    agent produced it look wrong, or the reverse.
    """

    def __init__(self, texts: dict[UUID, str]) -> None:
        self._texts = texts

    @property
    def message_ids(self) -> frozenset[UUID]:
        return frozenset(self._texts)

    def resolve(self, raw: Any) -> ResolvedSpan | None:
        """One span, or None. Never raises on malformed input.

        Called with whatever a model produced, so every field is treated as
        untrusted: a string where an integer belongs, a uuid that is not
        one, a missing key. All of those are "no evidence", not a crash.
        """
        if not isinstance(raw, dict):
            return None

        try:
            message_id = UUID(str(raw.get("message_id", "")))
        except (ValueError, AttributeError, TypeError):
            return None

        body = self._texts.get(message_id)
        if body is None:
            # Either not in this thread, or invented. Both are the same
            # answer: there is nothing here to quote.
            return None

        try:
            start = int(raw.get("char_start", -1))
            end = int(raw.get("char_end", -1))
        except (ValueError, TypeError):
            return None

        if start < 0 or end <= start or start >= len(body):
            return None

        end = min(end, len(body))
        quote = body[start:end].strip()
        if len(quote) < MIN_QUOTE_CHARS:
            return None

        if len(quote) > MAX_QUOTE_CHARS:
            quote = quote[: MAX_QUOTE_CHARS - 1].rstrip() + "…"

        return ResolvedSpan(message_id=message_id, char_start=start, char_end=end, quote=quote)

    def resolve_all(self, raws: Any) -> list[ResolvedSpan]:
        """Every span that resolves, in order. Silently drops the rest.

        Silently, because a partially evidenced claim is still evidenced:
        if three of five spans are good, the value stands on those three.
        What is never allowed is a claim standing on zero.
        """
        if not isinstance(raws, list):
            return []
        resolved = [span for span in (self.resolve(raw) for raw in raws) if span is not None]
        dropped = len(raws) - len(resolved)
        if dropped:
            log.info("evidence.spans_dropped", dropped=dropped, kept=len(resolved))
        return resolved


async def load_resolver(session: AsyncSession, thread_id: UUID) -> SpanResolver:
    """The stripped text of every live message in one thread.

    ``body_text_stripped`` and not the raw body, because that is what the
    context builder sent and what the agent counted against. Falling back
    to the snippet matches the same fallback there.
    """
    rows = (
        await session.execute(
            select(EmailMessage.id, EmailMessage.body_text_stripped, EmailMessage.snippet).where(
                EmailMessage.thread_id == thread_id,
                EmailMessage.deleted_at.is_(None),
            )
        )
    ).all()
    return SpanResolver({row[0]: str(row[1] or row[2] or "") for row in rows})


async def load_resolver_for_messages(
    session: AsyncSession, message_ids: list[UUID]
) -> SpanResolver:
    """A resolver over named messages, wherever they live.

    The companion cites across the whole mailbox, not one thread, so its
    citations cannot be checked by a per-thread resolver. The ids come
    from what the model produced, so the list is untrusted -- but RLS
    scopes the query to the armed tenant, which is what makes "a message
    id from another user's mail" resolve to nothing rather than to
    someone else's words. That is the user-A-never-sees-user-B gate
    holding at the one place a model could try to cross it.
    """
    if not message_ids:
        return SpanResolver({})

    rows = (
        await session.execute(
            select(EmailMessage.id, EmailMessage.body_text_stripped, EmailMessage.snippet).where(
                EmailMessage.id.in_(message_ids),
                EmailMessage.deleted_at.is_(None),
            )
        )
    ).all()
    return SpanResolver({row[0]: str(row[1] or row[2] or "") for row in rows})
