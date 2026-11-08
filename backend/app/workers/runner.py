"""The worker: claim, run, complete, repeat. One process, many job types.

Separate from the API because the two fail differently. An API that is
slow is a slow page; a worker that is slow is a backlog, and conflating
them means a sync storm takes the interface down with it.

The handler table is the only place a job type becomes code, so a type
with no handler is visible rather than a job that sits pending for ever.

Zero-LLM zone: this file schedules model work, it never does any.

    python -m app.workers.runner
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

from app.core.logging import bind_contextvars, configure_logging, get_logger
from app.database.engine import SessionFactory, dispose_engine
from app.jobs import queue

log = get_logger(__name__)

Handler = Callable[[queue.Job], Awaitable[None]]

#: How long to wait when the queue is empty. Short enough to feel live,
#: long enough not to be a busy loop against Postgres.
IDLE_SLEEP_SECONDS = 1.0

#: The reaper runs on this cadence, in the same loop. A separate process
#: for it would be another thing to keep alive for no benefit.
REAP_EVERY_SECONDS = 30.0

HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def decorate(handler: Handler) -> Handler:
        HANDLERS[job_type] = handler
        return handler

    return decorate


async def _handle_unknown(job: queue.Job) -> None:
    """A job type whose phase has not landed yet.

    Explicit rather than a silent default: an unhandled type should be
    visible in the log, not quietly marked complete.
    """
    log.warning("job.no_handler_yet", job_type=job.job_type, job_id=job.id)


async def run_one(*, worker_id: str = queue.WORKER_ID) -> bool:
    """Claim and run a single job. True when there was one."""
    async with SessionFactory() as session:
        async with session.begin():
            job = await queue.claim(session, worker_id=worker_id)
    if job is None:
        return False

    bind_contextvars(job_id=str(job.id), job_type=job.job_type)
    handler = HANDLERS.get(job.job_type, _handle_unknown)

    try:
        await handler(job)
    except Exception as exc:
        async with SessionFactory() as session:
            async with session.begin():
                status = await queue.fail(
                    session, job.id, error=f"{type(exc).__name__}: {exc}", worker_id=worker_id
                )
        log.warning("job.failed", job_id=job.id, status=status, error=str(exc)[:200])
        return True

    async with SessionFactory() as session:
        async with session.begin():
            await queue.complete(session, job.id, worker_id=worker_id)
    return True


async def main_loop(*, stop: asyncio.Event, worker_id: str = queue.WORKER_ID) -> None:
    last_reap = 0.0
    loop = asyncio.get_running_loop()

    while not stop.is_set():
        now = loop.time()
        if now - last_reap > REAP_EVERY_SECONDS:
            last_reap = now
            async with SessionFactory() as session:
                async with session.begin():
                    await queue.reap(session)

        did_work = await run_one(worker_id=worker_id)
        if not did_work:
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SLEEP_SECONDS)


async def serve() -> None:
    configure_logging()

    from app.modules.mcp import bootstrap

    bootstrap.build()

    # Importing the module is what registers the handlers. After the
    # runtime is built, because a handler may reference an agent.
    from app.workers import handlers  # noqa: F401

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)

    log.info("worker.started", worker_id=queue.WORKER_ID, handlers=sorted(HANDLERS))
    try:
        await main_loop(stop=stop)
    finally:
        await dispose_engine()
        log.info("worker.stopped")


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
