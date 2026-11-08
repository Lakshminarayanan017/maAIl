"""The Postgres job queue. No Redis, no Celery, no broker.

One datastore until a measured trigger says otherwise. Postgres does this
well enough with ``FOR UPDATE SKIP LOCKED``, and the operational saving of
not running a second stateful system is real.

Three properties this file exists to guarantee:

**The claim is one statement.** A SELECT followed by an UPDATE has a window
in which a worker can die holding nothing, or two workers can claim the same
row. The CTE below closes it: the row is locked, skipped by other claimers,
and marked running in the same statement.

**A dead worker's job comes back exactly once.** The lease is a timestamp,
not a lock held by a connection. When it expires the reaper returns the job
to ``pending`` with exponential backoff, or to ``dead`` if it has used its
attempts. A worker that wakes up after its lease expired cannot complete the
job, because completion checks the lease holder.

**A duplicate event reuses the job.** The partial unique index on
``dedupe_key`` means the second insert conflicts; this enqueues by upserting,
so a burst of five messages on one thread becomes one triage run (gap C5).

Zero-LLM zone.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import get_clock
from app.core.logging import get_logger

log = get_logger(__name__)

#: How long a worker may hold a job before the reaper assumes it died.
#: Long-running jobs renew rather than taking a longer lease: a long lease
#: is a long outage when a worker is killed.
LEASE_SECONDS = 300

#: Backoff is 30s * 2^attempts, so attempt 5 waits about sixteen minutes.
BACKOFF_BASE_SECONDS = 30

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


@dataclass(frozen=True)
class Job:
    id: int
    user_id: UUID | None
    job_type: str
    payload: dict[str, Any]
    dedupe_key: str | None
    attempts: int
    max_attempts: int
    lease_expires_at: datetime | None


#: Job types and their default priority. Lower runs first.
PRIORITIES: dict[str, int] = {
    "sync.initial_metadata": 10,
    "sync.delta": 20,
    "sync.reconcile": 30,
    "sync.initial_bodies": 40,
    "ingest.message": 50,
    "agent.triage": 60,
    "agent.specialist": 80,
    "scheduled.briefing": 120,
    "maintenance.purge": 200,
}

_ENQUEUE = text(
    """
    INSERT INTO background_jobs
        (user_id, job_type, payload, dedupe_key, priority, available_at, max_attempts)
    VALUES (:user_id, :job_type, :payload, :dedupe_key, :priority, :available_at, :max_attempts)
    ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending','running')
    DO UPDATE SET
        -- A later event for the same subject does not queue a second job.
        -- It keeps the earliest run time, so a burst debounces rather than
        -- being pushed back indefinitely by its own tail.
        payload = excluded.payload,
        available_at = least(background_jobs.available_at, excluded.available_at),
        priority = least(background_jobs.priority, excluded.priority),
        updated_at = now()
    RETURNING id, (xmax = 0) AS inserted
    """
)

#: One statement. A crash between choosing a row and marking it running is
#: not possible, because there is no between.
_CLAIM = text(
    """
    WITH claimed AS (
      SELECT id FROM background_jobs
       WHERE status = 'pending'
         AND available_at <= now()
         AND (CAST(:job_types AS text[]) IS NULL OR job_type = ANY(CAST(:job_types AS text[])))
       ORDER BY priority, available_at, id
       FOR UPDATE SKIP LOCKED
       LIMIT 1
    )
    UPDATE background_jobs j
       SET status = 'running',
           locked_by = :worker_id,
           lease_expires_at = now() + make_interval(secs => :lease_seconds),
           attempts = attempts + 1,
           updated_at = now()
      FROM claimed
     WHERE j.id = claimed.id
    RETURNING j.id, j.user_id, j.job_type, j.payload, j.dedupe_key,
              j.attempts, j.max_attempts, j.lease_expires_at
    """
)

#: Completion checks the lease holder. A worker that was reaped and then
#: woke up cannot mark its job done after someone else has taken it.
_COMPLETE = text(
    """
    UPDATE background_jobs
       SET status = 'completed', locked_by = NULL, lease_expires_at = NULL,
           last_error = NULL, updated_at = now()
     WHERE id = :job_id AND status = 'running' AND locked_by = :worker_id
    RETURNING id
    """
)

_FAIL = text(
    """
    UPDATE background_jobs
       SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
           available_at = now() + make_interval(
               secs => :backoff_base * power(2, least(attempts, 10))
           ),
           locked_by = NULL, lease_expires_at = NULL,
           last_error = :error, updated_at = now()
     WHERE id = :job_id AND status = 'running' AND locked_by = :worker_id
    RETURNING id, status
    """
)

_RENEW = text(
    """
    UPDATE background_jobs
       SET lease_expires_at = now() + make_interval(secs => :lease_seconds), updated_at = now()
     WHERE id = :job_id AND status = 'running' AND locked_by = :worker_id
    RETURNING lease_expires_at
    """
)

#: The reaper. Everything whose lease has expired comes back, or dies.
_REAP = text(
    """
    UPDATE background_jobs
       SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
           available_at = now() + make_interval(
               secs => :backoff_base * power(2, least(attempts, 10))
           ),
           locked_by = NULL, lease_expires_at = NULL,
           last_error = coalesce(last_error, 'lease expired'), updated_at = now()
     WHERE status = 'running' AND lease_expires_at < now()
    RETURNING id, status
    """
)


async def enqueue(
    session: AsyncSession,
    *,
    job_type: str,
    user_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    delay_seconds: float = 0.0,
    priority: int | None = None,
    max_attempts: int = 5,
) -> tuple[int, bool]:
    """Queue a job. Returns ``(job_id, newly_created)``.

    ``newly_created`` is False when an existing live job absorbed this
    one, which is the normal case under a burst and worth logging rather
    than hiding.
    """
    import json

    available_at = get_clock().now() + timedelta(seconds=delay_seconds)
    row = (
        await session.execute(
            _ENQUEUE,
            {
                "user_id": str(user_id) if user_id else None,
                "job_type": job_type,
                "payload": json.dumps(payload or {}),
                "dedupe_key": dedupe_key,
                "priority": priority if priority is not None else PRIORITIES.get(job_type, 100),
                "available_at": available_at,
                "max_attempts": max_attempts,
            },
        )
    ).one()
    job_id, inserted = int(row[0]), bool(row[1])
    if not inserted:
        log.info("job.deduped", job_type=job_type, dedupe_key=dedupe_key, job_id=job_id)
    return job_id, inserted


async def claim(
    session: AsyncSession,
    *,
    worker_id: str = WORKER_ID,
    job_types: list[str] | None = None,
    lease_seconds: int = LEASE_SECONDS,
) -> Job | None:
    """Take the next due job, or None."""
    row = (
        await session.execute(
            _CLAIM,
            {"worker_id": worker_id, "lease_seconds": lease_seconds, "job_types": job_types},
        )
    ).one_or_none()
    if row is None:
        return None
    return Job(
        id=int(row[0]),
        user_id=UUID(str(row[1])) if row[1] else None,
        job_type=row[2],
        payload=row[3] or {},
        dedupe_key=row[4],
        attempts=int(row[5]),
        max_attempts=int(row[6]),
        lease_expires_at=row[7],
    )


async def complete(session: AsyncSession, job_id: int, *, worker_id: str = WORKER_ID) -> bool:
    """Mark done. False when the lease had already been taken away."""
    done = (
        await session.execute(_COMPLETE, {"job_id": job_id, "worker_id": worker_id})
    ).one_or_none()
    if done is None:
        # The reaper got there first and someone else may now hold it.
        # Saying so is the difference between "exactly once" and "we hope".
        log.warning("job.complete_without_lease", job_id=job_id, worker_id=worker_id)
    return done is not None


async def fail(
    session: AsyncSession, job_id: int, *, error: str, worker_id: str = WORKER_ID
) -> str | None:
    """Return the job for a retry, or kill it. Gives back the new status."""
    row = (
        await session.execute(
            _FAIL,
            {
                "job_id": job_id,
                "worker_id": worker_id,
                "error": error[:1000],
                "backoff_base": BACKOFF_BASE_SECONDS,
            },
        )
    ).one_or_none()
    if row is None:
        return None
    status = str(row[1])
    if status == "dead":
        # Terminal and alertable. A dead job is work that will never happen
        # unless a person looks at it.
        log.error("job.dead", job_id=job_id, error=error[:200])
    return status


async def renew(
    session: AsyncSession,
    job_id: int,
    *,
    worker_id: str = WORKER_ID,
    lease_seconds: int = LEASE_SECONDS,
) -> bool:
    """Extend the lease mid-job. False means it was already reaped."""
    row = (
        await session.execute(
            _RENEW, {"job_id": job_id, "worker_id": worker_id, "lease_seconds": lease_seconds}
        )
    ).one_or_none()
    return row is not None


async def reap(session: AsyncSession) -> list[tuple[int, str]]:
    """Return expired jobs to the queue. Run periodically by the worker."""
    rows = (await session.execute(_REAP, {"backoff_base": BACKOFF_BASE_SECONDS})).all()
    reaped = [(int(row[0]), str(row[1])) for row in rows]
    if reaped:
        log.info("job.reaped", count=len(reaped), ids=[job_id for job_id, _ in reaped])
    return reaped


async def stats(session: AsyncSession) -> dict[str, int]:
    """Queue depth by status. Drives the H1 measurement views."""
    rows = (
        await session.execute(text("SELECT status, count(*) FROM background_jobs GROUP BY status"))
    ).all()
    return {str(row[0]): int(row[1]) for row in rows}
