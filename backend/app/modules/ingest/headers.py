"""RFC-822 header parsing. Deterministic, no model, no network.

Everything here uses the stdlib ``email`` package rather than regexes.
Address headers are a genuinely hard grammar -- quoted display names with
commas, group syntax, RFC-2047 encoded words -- and hand-rolling it is how
``"Smith, John" <j@x.test>`` becomes two recipients.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

__all__ = [
    "decode_mime_words",
    "message_id_list",
    "normalize_subject",
    "parse_address",
    "parse_address_list",
    "parse_date",
]

#: Reply and forward prefixes in the languages a mailbox actually mixes.
_PREFIX = re.compile(
    r"^\s*(?:(?:re|aw|antw|fwd?|vs|sv|tr|rif|res|回复|轉寄)\s*(?:\[\d+\])?\s*:\s*)+",
    re.IGNORECASE,
)
_MESSAGE_ID = re.compile(r"<[^<>\s]+>")


def decode_mime_words(value: str | None) -> str | None:
    """``=?utf-8?B?...?=`` to text. Returns the input if it will not decode."""
    if not value:
        return None
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


def parse_address(value: str | None) -> tuple[str | None, str | None]:
    """``(display name, address)`` from a From or Sender header."""
    if not value:
        return None, None
    pairs = getaddresses([value])
    if not pairs:
        return None, None
    name, address = pairs[0]
    return (decode_mime_words(name) or None), (address.strip().lower() or None)


def parse_address_list(value: str | None) -> list[str]:
    """Addresses only, lowercased, de-duplicated, order preserved."""
    if not value:
        return []
    seen: dict[str, None] = {}
    for _, address in getaddresses([value]):
        cleaned = address.strip().lower()
        if cleaned and "@" in cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def parse_date(value: str | None) -> tuple[datetime | None, int | None]:
    """``(instant in UTC, the sender's offset in minutes)``.

    The offset is kept because half of deadline resolution is relative: "by
    end of day tomorrow" means the sender's day, and throwing the offset
    away at parse time makes that unrecoverable (gap E2).
    """
    if not value:
        return None, None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        # A malformed Date header is normal, not exceptional. Gmail's
        # internalDate is the fallback, and the caller already has it.
        return None, None

    if parsed.tzinfo is None:
        # A Date header with no zone is not UTC, it is unknown. Treating it
        # as UTC is the least wrong option, and the null offset records
        # that the zone was never stated.
        return parsed.replace(tzinfo=timezone.utc), None

    offset = parsed.utcoffset()
    minutes = int(offset.total_seconds() // 60) if offset is not None else None
    return parsed.astimezone(timezone.utc), minutes


def message_id_list(value: str | None) -> list[str]:
    """Message-IDs out of a References or In-Reply-To header, in order."""
    if not value:
        return []
    found = _MESSAGE_ID.findall(value)
    if found:
        return found
    token = value.strip()
    return [token] if token else []


def normalize_subject(subject: str | None) -> str | None:
    """Strip reply and forward prefixes, collapse whitespace, casefold.

    Used only as a merge hint. Two threads with the same normalised subject
    are candidates for merging, never proof of it -- "Re: hello" is not an
    identity.
    """
    if not subject:
        return None
    stripped = _PREFIX.sub("", subject)
    collapsed = " ".join(stripped.split())
    return collapsed.casefold() or None
