"""A per-account token bucket for Gmail's quota.

Gmail's limit is **per minute**, not per day: 6,000 quota units per user per
minute, inside a 1,200,000/minute project ceiling. The unit prices are what
make this matter -- a full message fetch is 60 units, so the real budget is
about 100 full fetches a minute, and a naive loop hits
``userRateLimitExceeded`` within seconds of starting.

So the worker blocks on a bucket instead of discovering the limit the hard
way. Waiting is cheaper than a 429 plus a backoff plus a retry, and it keeps
the sync's throughput legible rather than sawtoothed.

The bucket is in-process, which is correct while there is one worker per
account and a per-account lock holds that true. When the job queue arrives in
phase 4 and more than one process can sync one account, this moves behind a
shared counter; the interface does not change.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app.core.clock import get_clock
from app.core.logging import get_logger

log = get_logger(__name__)

#: Quota units per call, from docs/architecture/00-gap-analysis.md §2 A1.
#: Kept in one place so a correction is one edit, not a search.
UNITS_LIST = 5
UNITS_GET_METADATA = 20
UNITS_GET_FULL = 60
UNITS_HISTORY_LIST = 2
UNITS_PROFILE = 1

#: 6,000 units per user per minute.
BUCKET_CAPACITY = 6000
REFILL_WINDOW_SECONDS = 60.0

#: Spend at most this share of the budget, so an interactive action (opening
#: a message body) is not starved by a backfill that is using every unit.
BACKGROUND_SHARE = 0.75


@dataclass
class TokenBucket:
    """Leaky bucket over the per-minute quota.

    Refills continuously rather than in steps: a step refill lets a burst
    land at the boundary and trip the limit the step was meant to avoid.
    """

    capacity: int = BUCKET_CAPACITY
    refill_per_second: float = BUCKET_CAPACITY / REFILL_WINDOW_SECONDS
    tokens: float = field(default=float(BUCKET_CAPACITY))
    updated_at: float = field(default=0.0)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.updated_at == 0.0:
            self.updated_at = get_clock().now().timestamp()

    def _replenish(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(float(self.capacity), self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now

    def wait_time(self, units: int) -> float:
        """Seconds until ``units`` are available. 0 when they already are."""
        self._replenish(get_clock().now().timestamp())
        if self.tokens >= units:
            return 0.0
        return (units - self.tokens) / self.refill_per_second

    async def acquire(self, units: int) -> float:
        """Block until ``units`` are available, then spend them.

        Returns how long it waited, which is the number worth logging: a
        sync that spends its time waiting on quota is a sync whose unit
        budget, not whose code, needs attention.
        """
        if units > self.capacity:
            raise ValueError(f"{units} units exceeds the bucket's capacity of {self.capacity}")

        waited = 0.0
        async with self._lock:
            while True:
                delay = self.wait_time(units)
                if delay <= 0:
                    self.tokens -= units
                    return waited
                waited += delay
                await asyncio.sleep(delay)


class QuotaLimiter:
    """One bucket per account, created on first use."""

    def __init__(self, capacity: int = BUCKET_CAPACITY) -> None:
        self._capacity = capacity
        self._buckets: dict[UUID, TokenBucket] = {}
        self._total_waited: dict[UUID, float] = {}

    def bucket(self, account_id: UUID) -> TokenBucket:
        bucket = self._buckets.get(account_id)
        if bucket is None:
            bucket = TokenBucket(
                capacity=self._capacity,
                refill_per_second=self._capacity / REFILL_WINDOW_SECONDS,
                tokens=float(self._capacity),
            )
            self._buckets[account_id] = bucket
        return bucket

    async def spend(self, account_id: UUID, units: int, *, what: str = "") -> float:
        waited = await self.bucket(account_id).acquire(units)
        if waited > 0:
            self._total_waited[account_id] = self._total_waited.get(account_id, 0.0) + waited
            log.info(
                "quota.waited",
                account_id=str(account_id),
                units=units,
                seconds=round(waited, 2),
                call=what,
            )
        return waited

    def waited_total(self, account_id: UUID) -> float:
        return self._total_waited.get(account_id, 0.0)

    def reset(self, account_id: UUID | None = None) -> None:
        if account_id is None:
            self._buckets.clear()
            self._total_waited.clear()
        else:
            self._buckets.pop(account_id, None)
            self._total_waited.pop(account_id, None)


#: The process-wide limiter. One worker per account makes this correct.
limiter = QuotaLimiter()
