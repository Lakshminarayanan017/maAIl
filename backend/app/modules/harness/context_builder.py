"""Assemble the smallest context that can answer the question.

Not "everything we know about this thread". A context builder that passes
the whole conversation is one that makes cost grow with the square of
thread length, which is exactly what quote stripping exists to stop.

Two rules:

**Stripped text only.** Every agent reads ``body_text_stripped``. Raw text
is for display and for resolving evidence offsets, never for prompts.

**Stable content first.** Provider prefix caching only pays when the start
of the prompt is byte-identical between calls, so the order is: system
prompt, then procedures, then the thread, then the question. Putting the
volatile part first turns a cache hit into a full-price call (gap B5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.thread import EmailMessage, EmailThread

#: Rough, and deliberately so. Four characters per token is close enough to
#: decide what to drop; the real count comes back from the provider.
CHARS_PER_TOKEN = 4


@dataclass
class BuiltContext:
    """What goes to the model, in prefix-cache order."""

    system: str
    procedures: str = ""
    thread_text: str = ""
    question: str = ""
    #: Messages left out because the budget ran out, oldest first.
    dropped_messages: int = 0
    estimated_tokens: int = 0
    message_ids: list[UUID] = field(default_factory=list)

    def render(self) -> str:
        parts = [self.system, self.procedures, self.thread_text, self.question]
        return "\n\n".join(part for part in parts if part)


#: The marker that makes a citation possible. An agent asked for evidence
#: has to say *which* message and *where* in it, and offsets into a
#: concatenated prompt resolve to nothing. So each block declares its
#: message id and states where zero is -- and ``harness/evidence.py``
#: later checks every span against exactly that text, which only works if
#: the two agree on where the body starts.
BODY_MARKER = "Body (character offsets below start at 0):"

#: The thread's own boundary. Everything between these two lines is
#: text other people wrote, and nothing outside them is.
THREAD_OPEN = '<thread source="the user\'s mailbox">'
THREAD_CLOSE = "</thread>"


def _block(message: EmailMessage) -> str:
    body = message.body_text_stripped or message.snippet or ""
    stamp = message.sent_at.strftime("%Y-%m-%d %H:%M")
    return (
        f"Message: {message.id}\nFrom: {message.from_email}\nDate: {stamp}\n{BODY_MARKER}\n{body}"
    )


async def build_thread_context(
    session: AsyncSession,
    *,
    thread_id: UUID,
    system: str,
    question: str = "",
    procedures: str = "",
    max_tokens: int = 4000,
) -> BuiltContext:
    """One thread, trimmed to fit, chronological in the prompt.

    Trimmed from the oldest end: a thread that does not fit is one where
    the recent messages matter and the opening ones are history. Dropping
    the old end keeps the part being replied to.
    """
    thread = await session.get(EmailThread, thread_id)
    if thread is None:
        return BuiltContext(system=system, question=question, procedures=procedures)

    messages = list(
        (
            await session.scalars(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread_id, EmailMessage.deleted_at.is_(None))
                .order_by(EmailMessage.sent_at.desc())
            )
        ).all()
    )

    fixed = len(system) + len(question) + len(procedures)
    budget_chars = max(0, max_tokens * CHARS_PER_TOKEN - fixed)

    chosen: list[EmailMessage] = []
    used = 0
    for message in messages:
        block = _block(message)
        if used + len(block) > budget_chars and chosen:
            break
        chosen.append(message)
        used += len(block)

    chosen.reverse()
    rendered = "\n\n---\n\n".join(_block(message) for message in chosen)
    header = f"Subject: {thread.subject or '(no subject)'}\n\n"

    # Delimited, and the closing tag is load-bearing twice over. It tells
    # the model exactly where the untrusted text stops, so a sentence in
    # an email cannot read as part of the instruction that follows it.
    # And it bounds the last message's body: without it, whatever comes
    # after the thread -- the question, the task -- is inside the final
    # block, and anything parsing that block back out picks it up. Found
    # by watching the prompt's own question appear as an action item.
    thread_text = f"{THREAD_OPEN}\n{header}{rendered}\n{THREAD_CLOSE}"

    return BuiltContext(
        system=system,
        procedures=procedures,
        thread_text=thread_text,
        question=question,
        dropped_messages=len(messages) - len(chosen),
        estimated_tokens=(fixed + len(thread_text)) // CHARS_PER_TOKEN,
        message_ids=[message.id for message in chosen],
    )
