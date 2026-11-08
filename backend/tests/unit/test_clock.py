"""The clock is injected, frozen in tests, and always timezone-aware."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.clock import FrozenClock, SystemClock, get_clock, in_timezone
from tests.conftest import FROZEN_NOW


def test_tests_run_on_a_stopped_clock() -> None:
    assert get_clock().now() == FROZEN_NOW


def test_frozen_clock_advances_only_when_told() -> None:
    clock = FrozenClock(FROZEN_NOW)
    assert clock.now() == FROZEN_NOW
    clock.advance(timedelta(days=4))
    assert clock.now() == FROZEN_NOW + timedelta(days=4)


def test_naive_datetimes_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 3, 11, 9, 30))


def test_system_clock_is_utc_aware() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_relative_dates_resolve_in_the_users_timezone() -> None:
    """09:30 UTC is the same evening in Kolkata and the same morning in New York.

    A deadline of "today" is a different instant for each, which is why
    users.timezone exists.
    """
    moment = datetime(2026, 3, 11, 22, 30, tzinfo=timezone.utc)
    assert in_timezone(moment, "Asia/Kolkata").date().isoformat() == "2026-03-12"
    assert in_timezone(moment, "America/New_York").date().isoformat() == "2026-03-11"
