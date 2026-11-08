"""Deterministic date candidates, with spans. No model, no guessing.

This finds the phrases that *might* be a deadline and says what kind each
one is. It does not decide whether a deadline exists, who it is for, or
whether it matters — that is the Deadline agent's job in phase 9, and it
will read these candidates rather than re-reading the prose.

Three rules, all from the gap analysis:

**A band, never a float.** ``"confidence": 0.94`` is theatre unless it has
been calibrated against something. A candidate is ``high``, ``medium`` or
``low``, and the rule that produced it is recorded (gap E1).

**Relative phrases resolve in the user's timezone**, against the message's
sent date, and the raw phrase travels alongside the resolved date so the UI
can always show what the sender actually wrote (gap E2).

**A span, always.** Every candidate carries the character offsets it came
from, so the interface can highlight the words rather than asserting a date
from nowhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

__all__ = ["DateCandidate", "DateKind", "find_date_candidates"]


class DateKind(str, Enum):
    """Matches ``date_type`` in the schema, so phase 9 stores it directly."""

    explicit_absolute = "explicit_absolute"
    explicit_relative = "explicit_relative"
    soft_request = "soft_request"
    vague = "vague"
    recurring = "recurring"


@dataclass(frozen=True)
class DateCandidate:
    text: str
    start: int
    end: int
    kind: DateKind
    #: Null when the phrase names no resolvable day ("as soon as possible").
    resolved: date | None
    confidence_band: str
    #: Which rule fired. Makes a wrong candidate debuggable rather than
    #: mysterious, and gives the UI something honest to show.
    rule: str


_MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}
_MONTHS.update({name[:3]: index for name, index in list(_MONTHS.items())})

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "tues": 1,
    "wed": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}

_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_NAMES = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))

# --- absolute --------------------------------------------------------------
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAMES})\.?(?:\s+(\d{{4}}))?\b",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b",
    re.IGNORECASE,
)

# --- relative --------------------------------------------------------------
_TODAY = re.compile(r"\b(today|tonight)\b", re.IGNORECASE)
_TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
_IN_N = re.compile(r"\bin\s+(\d{1,3})\s+(day|week|month)s?\b", re.IGNORECASE)
_WEEKDAY = re.compile(rf"\b(this|next|by|before|on)?\s*({_WEEKDAY_NAMES})\b", re.IGNORECASE)
_END_OF = re.compile(
    r"\b(?:by\s+)?(?:the\s+)?end\s+of\s+(?:the\s+)?(day|week|month|business\s+day)\b",
    re.IGNORECASE,
)
_EOD = re.compile(r"\b(eod|cob|eow)\b", re.IGNORECASE)

# --- soft and vague --------------------------------------------------------
_SOFT = re.compile(
    r"\b(?:as\s+soon\s+as\s+possible|asap|at\s+your\s+earliest\s+convenience"
    r"|when\s+you\s+(?:get\s+a\s+)?(?:can|chance)|whenever\s+you\s+can"
    r"|no\s+rush|when\s+convenient)\b",
    re.IGNORECASE,
)
_VAGUE = re.compile(r"\b(?:soon|shortly|in\s+due\s+course|before\s+long)\b", re.IGNORECASE)

# --- recurring -------------------------------------------------------------
_RECURRING = re.compile(
    rf"\b(?:every\s+(?:{_WEEKDAY_NAMES}|day|week|month)"
    r"|daily|weekly|fortnightly|monthly|quarterly)\b",
    re.IGNORECASE,
)


def find_date_candidates(
    text: str | None,
    *,
    sent_at: datetime,
    user_timezone: str = "UTC",
) -> list[DateCandidate]:
    """Every date-ish phrase in ``text``, with where it was and what it means.

    ``sent_at`` anchors the relative phrases and ``user_timezone`` decides
    whose day boundary "tomorrow" crosses. Both matter: a message sent at
    22:30 UTC was sent on a different calendar day in Kolkata than in New
    York, and so is its "tomorrow".
    """
    if not text:
        return []

    try:
        anchor = sent_at.astimezone(ZoneInfo(user_timezone)).date()
    except Exception:
        anchor = sent_at.date()

    found: list[DateCandidate] = []
    found += _absolute(text, anchor)
    found += _relative(text, anchor)
    found += _simple(text, _RECURRING, DateKind.recurring, "medium", "recurring")
    found += _simple(text, _SOFT, DateKind.soft_request, "medium", "soft-request")
    found += _simple(text, _VAGUE, DateKind.vague, "low", "vague")

    return _dedupe(found)


# ---------------------------------------------------------------------------
def _absolute(text: str, anchor: date) -> list[DateCandidate]:
    out: list[DateCandidate] = []

    for match in _ISO.finditer(text):
        resolved = _safe_date(int(match[1]), int(match[2]), int(match[3]))
        if resolved:
            out.append(_candidate(match, DateKind.explicit_absolute, resolved, "high", "iso-8601"))

    for pattern, rule, day_first in (
        (_DAY_MONTH, "day-month", True),
        (_MONTH_DAY, "month-day", False),
    ):
        for match in pattern.finditer(text):
            day = int(match[1] if day_first else match[2])
            month = _MONTHS[(match[2] if day_first else match[1]).lower().rstrip(".")]
            year = int(match[3]) if match[3] else _nearest_year(anchor, month, day)
            resolved = _safe_date(year, month, day)
            if resolved:
                band = "high" if match[3] else "medium"
                out.append(_candidate(match, DateKind.explicit_absolute, resolved, band, rule))

    return out


def _relative(text: str, anchor: date) -> list[DateCandidate]:
    out: list[DateCandidate] = []

    for match in _TODAY.finditer(text):
        out.append(_candidate(match, DateKind.explicit_relative, anchor, "high", "today"))

    for match in _TOMORROW.finditer(text):
        out.append(
            _candidate(
                match, DateKind.explicit_relative, anchor + timedelta(days=1), "high", "tomorrow"
            )
        )

    for match in _IN_N.finditer(text):
        count = int(match[1])
        unit = match[2].lower()
        days = count * {"day": 1, "week": 7, "month": 30}[unit]
        out.append(
            _candidate(
                match,
                DateKind.explicit_relative,
                anchor + timedelta(days=days),
                "high" if unit != "month" else "medium",
                f"in-n-{unit}s",
            )
        )

    for match in _END_OF.finditer(text):
        unit = match[1].lower().replace("business ", "")
        if unit == "day":
            resolved = anchor
        elif unit == "week":
            resolved = anchor + timedelta(days=(4 - anchor.weekday()) % 7)
        else:
            resolved = _end_of_month(anchor)
        out.append(
            _candidate(match, DateKind.explicit_relative, resolved, "medium", f"end-of-{unit}")
        )

    for match in _EOD.finditer(text):
        token = match[1].lower()
        resolved = (
            anchor
            if token in ("eod", "cob")
            else anchor + timedelta(days=(4 - anchor.weekday()) % 7)
        )
        out.append(_candidate(match, DateKind.explicit_relative, resolved, "medium", token))

    for match in _WEEKDAY.finditer(text):
        qualifier = (match[1] or "").strip().lower()
        weekday = _WEEKDAYS[match[2].lower()]
        # A bare weekday with no qualifier is usually prose ("the Friday
        # release"), so it is a low-confidence candidate rather than a date.
        band = "medium" if qualifier else "low"
        ahead = (weekday - anchor.weekday()) % 7
        if qualifier == "next":
            ahead = ahead + 7 if ahead else 7
        elif ahead == 0:
            ahead = 7 if qualifier in ("", "next") else 0
        out.append(
            _candidate(
                match,
                DateKind.explicit_relative,
                anchor + timedelta(days=ahead),
                band,
                f"weekday-{qualifier or 'bare'}",
            )
        )

    return out


def _simple(
    text: str, pattern: re.Pattern[str], kind: DateKind, band: str, rule: str
) -> list[DateCandidate]:
    return [_candidate(match, kind, None, band, rule) for match in pattern.finditer(text)]


def _candidate(
    match: re.Match[str], kind: DateKind, resolved: date | None, band: str, rule: str
) -> DateCandidate:
    return DateCandidate(
        text=match.group(0).strip(),
        start=match.start(),
        end=match.end(),
        kind=kind,
        resolved=resolved,
        confidence_band=band,
        rule=rule,
    )


def _dedupe(found: list[DateCandidate]) -> list[DateCandidate]:
    """Keep the strongest candidate per overlapping span.

    "31 March 2026" matches both the day-month rule and, inside it, nothing
    else — but "Friday" inside "by Friday" would otherwise appear twice.
    Longer spans win; equal spans are broken by confidence.
    """
    order = {"high": 0, "medium": 1, "low": 2}
    ranked = sorted(found, key=lambda c: (-(c.end - c.start), order[c.confidence_band], c.start))

    kept: list[DateCandidate] = []
    for candidate in ranked:
        if any(candidate.start < other.end and other.start < candidate.end for other in kept):
            continue
        kept.append(candidate)
    return sorted(kept, key=lambda c: c.start)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _nearest_year(anchor: date, month: int, day: int) -> int:
    """A date with no year means the next one, not an arbitrary one.

    "the 3rd of April" sent in November means next April. Choosing this
    year would silently resolve a deadline into the past.
    """
    candidate = _safe_date(anchor.year, month, day)
    if candidate is None:
        return anchor.year
    return anchor.year if candidate >= anchor - timedelta(days=14) else anchor.year + 1


def _end_of_month(anchor: date) -> date:
    if anchor.month == 12:
        return date(anchor.year, 12, 31)
    return date(anchor.year, anchor.month + 1, 1) - timedelta(days=1)
