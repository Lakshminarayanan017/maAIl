"""The clock, as an injected dependency.

Half of ``deadlines`` is relative-date resolution — "by end of next week", "EOD
Friday". A test suite whose answers change on Friday is not a test suite, so
nothing in Maail calls ``datetime.now()`` directly. ``tests/arch`` enforces it.

See docs/architecture/07-harness.md §8.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, always timezone-aware and in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin, never going backwards.

        A separate question from ``now()``. Measuring how long a run has
        taken must not be affected by an NTP correction, and asking "what
        day is it" must not be answered by a counter since boot. Both are
        here so both are controllable from a test.
        """
        ...


class SystemClock:
    """Production clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class FrozenClock:
    """Test clock. Advances only when a test says so."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at.astimezone(timezone.utc)
        self._elapsed = 0.0

    def now(self) -> datetime:
        return self._at

    def monotonic(self) -> float:
        """Advances exactly as far as ``advance`` was told to move.

        So a test can prove a wall-clock cap fires without waiting for it.
        """
        return self._elapsed

    def advance(self, delta: timedelta) -> datetime:
        self._at += delta
        self._elapsed += delta.total_seconds()
        return self._at

    def set(self, at: datetime) -> datetime:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at.astimezone(timezone.utc)
        return self._at


_clock: Clock = SystemClock()


def get_clock() -> Clock:
    """FastAPI dependency and module-level accessor."""
    return _clock


def set_clock(clock: Clock) -> None:
    """Test-only. Replaces the process clock."""
    global _clock
    _clock = clock


def in_timezone(moment: datetime, tz_name: str) -> datetime:
    """Render a UTC instant in a user's timezone.

    Relative dates resolve against the *user's* day boundary, not the server's.
    ``users.timezone`` exists for this (02-lld-data-model.md §1).
    """
    return moment.astimezone(ZoneInfo(tz_name))
