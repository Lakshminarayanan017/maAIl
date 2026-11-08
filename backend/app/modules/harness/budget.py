"""Per-user spending caps, enforced before the model call.

"Summarise my entire inbox" fans out without limit, and one user can burn a
month of budget in one request (gap B3). Reconciling afterwards tells you
what happened; it does not stop it.

Two caps, because they mean different things. The soft cap warns and keeps
going — the person should know, not be cut off mid-task. The hard cap
declines with a clear message, which is better than a silently degraded
product that stops explaining itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.logging import get_logger

log = get_logger(__name__)

#: Defaults for a new user, in micros (one millionth of a currency unit).
#: Deliberately small: the cost model says a month of normal use is well
#: under this, so hitting it means something is wrong.
DEFAULT_SOFT_CAP_MICROS = 2_000_000  # 2.00
DEFAULT_HARD_CAP_MICROS = 5_000_000  # 5.00


class BudgetState(str, Enum):
    ok = "ok"
    soft_exceeded = "soft_exceeded"
    hard_exceeded = "hard_exceeded"


@dataclass(frozen=True)
class BudgetCheck:
    state: BudgetState
    spent_micros: int
    soft_cap_micros: int
    hard_cap_micros: int

    @property
    def allowed(self) -> bool:
        return self.state is not BudgetState.hard_exceeded

    @property
    def remaining_micros(self) -> int:
        return max(0, self.hard_cap_micros - self.spent_micros)


_ENSURE = text(
    """
    INSERT INTO usage_budgets (user_id, period_month, soft_cap_micros, hard_cap_micros)
    VALUES (:user_id, :month, :soft, :hard)
    ON CONFLICT (user_id, period_month) DO NOTHING
    """
)

_READ = text(
    """
    SELECT spent_micros, soft_cap_micros, hard_cap_micros
      FROM usage_budgets WHERE user_id = :user_id AND period_month = :month
    """
)

#: Atomic, so two concurrent runs cannot both read the same balance and
#: both decide there is room for one more.
_SPEND = text(
    """
    UPDATE usage_budgets
       SET spent_micros = spent_micros + :amount
     WHERE user_id = :user_id AND period_month = :month
    RETURNING spent_micros, soft_cap_micros, hard_cap_micros
    """
)


def _month(when: date | None = None) -> date:
    today = when or get_clock().now().date()
    return today.replace(day=1)


async def check(session: AsyncSession, user_id: UUID) -> BudgetCheck:
    """Where this user stands this month. Call before the model, not after."""
    month = _month()
    await session.execute(
        _ENSURE,
        {
            "user_id": str(user_id),
            "month": month,
            "soft": DEFAULT_SOFT_CAP_MICROS,
            "hard": DEFAULT_HARD_CAP_MICROS,
        },
    )
    row = (await session.execute(_READ, {"user_id": str(user_id), "month": month})).one()
    return _state(int(row[0]), int(row[1]), int(row[2]))


async def spend(session: AsyncSession, user_id: UUID, micros: int) -> BudgetCheck:
    """Record what a run cost. Returns the new standing."""
    month = _month()
    await session.execute(
        _ENSURE,
        {
            "user_id": str(user_id),
            "month": month,
            "soft": DEFAULT_SOFT_CAP_MICROS,
            "hard": DEFAULT_HARD_CAP_MICROS,
        },
    )
    row = (
        await session.execute(
            _SPEND, {"user_id": str(user_id), "month": month, "amount": max(0, micros)}
        )
    ).one()
    result = _state(int(row[0]), int(row[1]), int(row[2]))
    if result.state is not BudgetState.ok:
        log.warning(
            "budget.exceeded",
            user_id=str(user_id),
            state=result.state.value,
            spent_micros=result.spent_micros,
        )
    return result


def _state(spent: int, soft: int, hard: int) -> BudgetCheck:
    if spent >= hard:
        state = BudgetState.hard_exceeded
    elif spent >= soft:
        state = BudgetState.soft_exceeded
    else:
        state = BudgetState.ok
    return BudgetCheck(state=state, spent_micros=spent, soft_cap_micros=soft, hard_cap_micros=hard)
