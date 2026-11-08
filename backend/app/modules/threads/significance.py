"""The significance gate: what stops a busy thread costing six runs an hour.

Pure code, no model (gap C5). A mailing-list thread with forty replies
should cost one triage, not forty, and deciding that with a model would
cost exactly what it is meant to save.

Asymmetric on purpose, like the Triage bypass: every rule that returns
False needs positive evidence that nothing changed. The default when in
doubt is to reprocess, because the cost of over-processing is a bill and
the cost of under-processing is a missed deadline.

See docs/architecture/03-lld-agent-runtime.md §6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.modules.ingest.date_parser import find_date_candidates

#: Senders that are machines. A first human reply to an automated thread
#: is the moment it starts mattering.
_AUTOMATION = re.compile(
    r"^(?:no-?reply|do-?not-?reply|notifications?|alerts?|mailer|bounce|postmaster"
    r"|automated|jenkins|ci|build|github|gitlab|jira|support)[.+@_-]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Significance:
    reprocess: bool
    reason: str


def is_automation(address: str | None) -> bool:
    return bool(address) and bool(_AUTOMATION.match(str(address)))


def user_named_directly(text: str | None, *, names: tuple[str, ...]) -> bool:
    """Whether the message addresses the user by name.

    Being named in a forty-person thread is the difference between reading
    it and ignoring it, and it is cheap to detect.
    """
    if not text or not names:
        return False
    lowered = text.lower()
    return any(name.lower() in lowered for name in names if len(name) >= 3)


def should_reprocess(
    *,
    has_intelligence: bool,
    message_is_from_user: bool,
    sender: str | None,
    known_participants: frozenset[str],
    body_text: str | None,
    sent_at: datetime | None = None,
    user_names: tuple[str, ...] = (),
    thread_was_automation_only: bool = False,
    current_priority: int | None = None,
) -> Significance:
    """Whether this new message is worth another look."""
    if not has_intelligence:
        return Significance(True, "first_pass")

    if message_is_from_user:
        # Your own reply does not change what the thread is about. It does
        # clear needs_reply, which the caller does deterministically.
        return Significance(False, "own_message")

    normalised = (sender or "").lower()
    if normalised and normalised not in known_participants:
        return Significance(True, "new_participant")

    if user_named_directly(body_text, names=user_names):
        return Significance(True, "user_addressed")

    if body_text and sent_at is not None and find_date_candidates(body_text, sent_at=sent_at):
        return Significance(True, "date_phrase_present")

    if thread_was_automation_only and not is_automation(sender):
        return Significance(True, "first_human_reply")

    if current_priority is not None and current_priority >= 2:
        # Already important. A thread that mattered yesterday is worth
        # re-reading today, even for a routine-looking reply.
        return Significance(True, "already_high_priority")

    return Significance(False, "no_significant_change")
