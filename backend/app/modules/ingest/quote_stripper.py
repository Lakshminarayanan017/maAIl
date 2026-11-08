"""Quote and signature removal. The single largest cost lever in Maail.

In a ten-message thread, message ten quotes messages one to nine. Feed raw
bodies to a model and the bill grows roughly with the square of the thread
length. Stripping the quoted chain removes 60-80% of a reply's text, and it
costs no model call at all (gap B1).

Two rules shape the implementation:

**Never lose new content.** Every heuristic here is conservative: when a
marker is ambiguous, the text stays. Over-stripping silently deletes the
sentence an agent needed; under-stripping only costs tokens.

**Offsets must survive.** Evidence spans point into the *raw* text, so the
stripper returns the character ranges it removed rather than only the
shortened string. A quote with an offset nobody can map back is a quote the
user cannot verify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["StripResult", "strip_quotes"]

#: "On Tue, 10 Mar 2026 at 09:00, Someone <a@b> wrote:" and its variants.
#: Requires the trailing colon, so a sentence beginning "On Monday we..."
#: is not mistaken for an attribution line.
_ATTRIBUTION = re.compile(
    r"""^\s*
    (?:
        on\s.{0,200}?\swrote\s*:          # English
      | le\s.{0,200}?\sa\s+écrit\s*:      # French
      | am\s.{0,200}?\sschrieb\s.{0,80}:  # German
      | el\s.{0,200}?\sescribió\s*:       # Spanish
      | .{0,80}\swrote\s*:                # bare "Someone wrote:"
    )\s*$""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

#: Outlook and friends: a header block introducing the quoted message.
_FORWARD_HEADER = re.compile(
    r"^\s*(?:-{2,}\s*)?(?:original message|forwarded message|begin forwarded message)"
    r"\s*(?:-{2,})?\s*$",
    re.IGNORECASE,
)

#: "From: ... Sent: ... To: ... Subject: ..." stacked under a divider.
_HEADER_LINE = re.compile(r"^\s*(?:from|sent|to|cc|subject|date|reply-to)\s*:\s?.*$", re.IGNORECASE)

#: Gmail's own divider, and the common horizontal rules clients insert.
_DIVIDER = re.compile(r"^\s*(?:_{5,}|-{5,}|\*{5,})\s*$")

#: RFC 3676 signature delimiter. Exactly "-- ", and tolerated without the
#: trailing space because half of all clients strip it.
_SIGNATURE = re.compile(r"^--\s?$")

#: Footers that are never content. Deliberately short: a list that tries to
#: catch every marketing footer will eventually eat a real sentence.
_FOOTER = re.compile(
    r"^\s*(?:"
    r"sent from my \w+"
    r"|get outlook for \w+"
    r"|this e?-?mail (?:and any attachments )?(?:is|are) confidential"
    r"|unsubscribe\b.{0,60}"
    r"|you are receiving this (?:e?-?mail|message) because"
    r")\s*\.?\s*$",
    re.IGNORECASE,
)

#: A quoted line. ">" possibly repeated, possibly after whitespace.
_QUOTED = re.compile(r"^\s*>")

#: A signature block cannot reasonably be longer than this many lines, so a
#: "-- " in the middle of a long message is treated as content.
MAX_SIGNATURE_LINES = 12


@dataclass
class StripResult:
    """What survived, and exactly what did not."""

    text: str
    #: ``(start, end)`` character ranges removed from the input, in order.
    #: Evidence offsets resolve against the original through these.
    removed_spans: list[tuple[int, int]] = field(default_factory=list)
    #: 0.0 when nothing was removed, 0.8 when four fifths was.
    ratio: float = 0.0
    #: Set when a reply's quoted chain was found, which is what the cost
    #: measurement is actually about.
    found_quote: bool = False
    found_signature: bool = False

    @property
    def removed_chars(self) -> int:
        return sum(end - start for start, end in self.removed_spans)


def strip_quotes(body: str | None) -> StripResult:
    """Remove quoted history and the trailing signature.

    Scans line by line and cuts at the first marker that begins the quoted
    tail, rather than deleting quoted lines wherever they appear. A reply
    interleaved with quotes keeps its new sentences; only the trailing chain
    goes, because that is the part that is reliably redundant.
    """
    if not body:
        return StripResult(text="", ratio=0.0)

    lines = body.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    cut_at = _find_quote_start(lines)
    found_quote = cut_at is not None
    if cut_at is None:
        cut_at = len(lines)

    signature_at = _find_signature_start(lines, limit=cut_at)
    found_signature = signature_at is not None
    if signature_at is not None:
        cut_at = signature_at

    removed: list[tuple[int, int]] = []
    if cut_at < len(lines):
        removed.append((offsets[cut_at], len(body)))

    kept = "".join(lines[:cut_at])

    # Trailing footers that sit above the cut, such as a mobile signature
    # with no "-- " before it.
    kept, footer_removed = _trim_footers(kept)
    if footer_removed:
        removed.insert(0, (len(kept.rstrip()), len(kept.rstrip()) + footer_removed))

    text = kept.strip()
    original_length = len(body.strip())
    ratio = 0.0 if original_length == 0 else 1 - (len(text) / original_length)

    return StripResult(
        text=text,
        removed_spans=removed,
        ratio=max(0.0, round(ratio, 4)),
        found_quote=found_quote,
        found_signature=found_signature,
    )


def _find_quote_start(lines: list[str]) -> int | None:
    """The first line of the trailing quoted chain, or None.

    Looks for an attribution line, a forwarded-message header, or a run of
    ``>`` lines that continues to the end. The run has to reach the end:
    quoted lines in the middle of a reply are someone answering inline, and
    the answers around them are exactly what must survive.
    """
    for index, line in enumerate(lines):
        stripped = line.strip()

        if _FORWARD_HEADER.match(stripped):
            return index

        if _ATTRIBUTION.match(stripped):
            return index

        if _DIVIDER.match(stripped) and _header_block_follows(lines, index + 1):
            return index

        if _QUOTED.match(line) and _quoted_to_the_end(lines, index):
            return index

    return None


def _header_block_follows(lines: list[str], start: int) -> bool:
    """At least two stacked ``From:``/``Sent:`` style lines after a divider."""
    seen = 0
    for line in lines[start : start + 6]:
        if not line.strip():
            continue
        if _HEADER_LINE.match(line):
            seen += 1
            if seen >= 2:
                return True
        else:
            return False
    return False


def _quoted_to_the_end(lines: list[str], start: int) -> bool:
    """Whether everything from here on is quoted or blank."""
    for line in lines[start:]:
        if not line.strip():
            continue
        if not _QUOTED.match(line):
            return False
    return True


def _find_signature_start(lines: list[str], *, limit: int) -> int | None:
    """The last ``-- `` delimiter with a short block under it."""
    for index in range(limit - 1, -1, -1):
        if _SIGNATURE.match(lines[index].rstrip("\r\n")):
            remaining = limit - index - 1
            if remaining <= MAX_SIGNATURE_LINES:
                return index
            # A "-- " with a long tail is a horizontal rule in the middle of
            # a message, not a signature.
            return None
    return None


def _trim_footers(text: str) -> tuple[str, int]:
    """Drop trailing footer lines. Returns the text and how much went."""
    lines = text.splitlines()
    removed = 0
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if _FOOTER.match(last):
            removed += len(lines.pop()) + 1
            continue
        break
    return "\n".join(lines), removed
