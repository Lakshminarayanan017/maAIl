"""Tier 0: a provider payload becomes a row shape. No model, ever.

The whole pipeline runs here: HTML to text, then quote and signature
removal into ``body_text_stripped`` with the ratio recorded. Every agent
reads the stripped column; the raw text stays for display and for resolving
evidence offsets.

``body_text_stripped`` stays NULL when there is no body yet, which is a
different thing from "stripped, nothing to remove" -- that case is an empty
string with a ratio of zero. Pass 2 of the sync depends on telling them
apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.modules.ingest.headers import (
    decode_mime_words,
    message_id_list,
    normalize_subject,
    parse_address,
    parse_address_list,
    parse_date,
)
from app.modules.ingest.html_to_text import html_to_text
from app.modules.ingest.quote_stripper import strip_quotes
from app.modules.providers.email.base import RawAttachment, RawMessage

__all__ = ["NormalisedMessage", "normalise"]

#: Gmail label ids that mean something to Maail rather than to Gmail.
LABEL_UNREAD = "UNREAD"
LABEL_SENT = "SENT"
LABEL_DRAFT = "DRAFT"


@dataclass(frozen=True)
class NormalisedMessage:
    provider_message_id: str
    provider_thread_id: str

    rfc822_message_id: str | None
    in_reply_to: str | None
    references_ids: list[str]

    from_email: str | None
    from_name: str | None
    to_emails: list[str]
    cc_emails: list[str]
    subject: str | None
    subject_normalized: str | None

    sent_at: datetime
    sender_tz_offset_min: int | None

    snippet: str | None
    body_text: str | None
    #: Quoted history and signature removed. The column every agent reads.
    body_text_stripped: str | None
    #: How much came off, 0.0 to 1.0. Observability on the biggest cost
    #: lever in the project, so a regression in the stripper is visible.
    stripped_ratio: float | None
    size_bytes: int | None

    is_from_user: bool
    is_read: bool
    is_draft: bool
    provider_labels: list[str]
    has_body: bool
    attachments: list[RawAttachment] = field(default_factory=list)

    @property
    def participants(self) -> list[str]:
        """Everyone on the message, de-duplicated, order preserved."""
        seen: dict[str, None] = {}
        for address in [self.from_email, *self.to_emails, *self.cc_emails]:
            if address:
                seen.setdefault(address.lower(), None)
        return list(seen)

    @property
    def thread_hints(self) -> list[str]:
        """RFC-822 ids this message claims to continue, nearest first.

        ``In-Reply-To`` is the direct parent and the strongest signal;
        ``References`` is the chain behind it, reversed so the nearest
        ancestor is tried first.
        """
        hints: list[str] = []
        if self.in_reply_to:
            hints.append(self.in_reply_to)
        hints.extend(reversed(self.references_ids))
        seen: dict[str, None] = {}
        for hint in hints:
            seen.setdefault(hint, None)
        return list(seen)


def normalise(raw: RawMessage, *, account_email: str | None = None) -> NormalisedMessage:
    headers = {name.lower(): value for name, value in raw.headers.items()}

    from_name, from_email = parse_address(headers.get("from"))
    sent_at, offset = parse_date(headers.get("date"))
    subject = decode_mime_words(headers.get("subject"))

    references = message_id_list(headers.get("references"))
    in_reply_to_list = message_id_list(headers.get("in-reply-to"))
    rfc822 = message_id_list(headers.get("message-id"))

    labels = list(raw.label_ids)

    # Gmail's SENT label is the reliable signal; the From address is not,
    # because a person can send from an alias Maail has never been told
    # about (gap A6).
    is_from_user = LABEL_SENT in labels or (
        account_email is not None
        and from_email is not None
        and from_email.lower() == account_email.lower()
    )

    body_text = raw.body_text or html_to_text(raw.body_html)

    # The single largest cost saving in Maail, and it uses no model at all.
    stripped: str | None = None
    ratio: float | None = None
    if raw.has_body and body_text is not None:
        result = strip_quotes(body_text)
        stripped, ratio = result.text, result.ratio

    return NormalisedMessage(
        provider_message_id=raw.provider_message_id,
        provider_thread_id=raw.provider_thread_id,
        rfc822_message_id=rfc822[0] if rfc822 else None,
        in_reply_to=in_reply_to_list[0] if in_reply_to_list else None,
        references_ids=references,
        from_email=from_email,
        from_name=from_name,
        to_emails=parse_address_list(headers.get("to")),
        cc_emails=parse_address_list(headers.get("cc")),
        subject=subject,
        subject_normalized=normalize_subject(subject),
        # internalDate is Gmail's receipt time and always present; the Date
        # header is the sender's claim and sometimes absent or nonsense.
        sent_at=sent_at or raw.received_at,
        sender_tz_offset_min=offset,
        snippet=raw.snippet,
        body_text=body_text,
        body_text_stripped=stripped,
        stripped_ratio=ratio,
        size_bytes=raw.size_bytes,
        is_from_user=is_from_user,
        is_read=LABEL_UNREAD not in labels,
        is_draft=LABEL_DRAFT in labels,
        provider_labels=labels,
        has_body=raw.has_body,
        attachments=list(raw.attachments),
    )
