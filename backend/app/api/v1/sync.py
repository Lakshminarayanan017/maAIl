"""Trigger a sync and watch it. Zero LLM.

Phase 2 runs the sync as an asyncio task with a per-account lock. That is
deliberately the smallest thing that satisfies the phase's demo — kill it
mid-run and it resumes — because progress lives in the database, not in the
task. Phase 4 replaces the task with a queued job and a lease; the endpoints
and the status shape do not change.

Status is Server-Sent Events rather than WebSockets: it is one-directional,
it reconnects by itself, and it survives a proxy that has never heard of
WebSockets.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import AuthContext, require_csrf
from app.core.logging import get_logger
from app.core.tenancy import tenant_session
from app.modules.accounts import service
from app.modules.accounts.service import AccountNotFound
from app.modules.providers.email.gmail import GmailClient
from app.modules.providers.oauth.google import GoogleOAuthClient
from app.modules.sync import engine

router = APIRouter(prefix="/sync", tags=["sync"])
log = get_logger(__name__)

#: How often the stream emits while a sync is running. Fast enough that a
#: progress bar moves, slow enough that it is not a busy loop.
TICK_SECONDS = 1.0

#: A browser will reconnect an SSE stream by itself; this bounds how long
#: one connection holds a worker.
MAX_STREAM_SECONDS = 600


class SyncStarted(BaseModel):
    account_id: UUID
    phase: str
    already_running: bool = False


class SyncStatus(BaseModel):
    account_id: UUID
    phase: str
    done: int
    total: int | None
    threads: int
    new_messages: int
    misses: int
    error: str | None


def _provider_factory(account_id: UUID) -> Callable[[str], GmailClient]:
    def build(access_token: str) -> GmailClient:
        return GmailClient(account_id=account_id, access_token=access_token)

    return build


@router.post(
    "/trigger",
    response_model=SyncStarted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_csrf)],
    summary="Start a sync for an account",
)
async def trigger(
    auth: AuthContext,
    account_id: Annotated[UUID, Query()],
    full: Annotated[bool, Query()] = False,
) -> SyncStarted:
    try:
        account = await service.get_account(auth.session, account_id)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account") from exc

    running = engine.progress_for(account.id)
    if running is not None and not running.finished:
        return SyncStarted(account_id=account.id, phase=running.phase, already_running=True)

    user_id = auth.user_id
    target = account.id

    async def run() -> None:
        try:
            await engine.sync_account(
                user_id=user_id,
                account_id=target,
                provider_factory=_provider_factory(target),
                oauth_client=GoogleOAuthClient(),
                full=full,
            )
        except engine.SyncAlreadyRunning:
            pass
        except Exception:
            log.exception("sync.task_crashed", account_id=str(target))

    # Not awaited: the caller gets 202 and watches the stream. The task
    # holds no request state, so the response finishing does not cancel it.
    task = asyncio.create_task(run(), name=f"sync-{target}")
    _background.add(task)
    task.add_done_callback(_background.discard)

    return SyncStarted(account_id=account.id, phase="starting")


#: Strong references, because asyncio only holds weak ones and a garbage
#: collected task is a sync that stops halfway for no visible reason.
_background: set[asyncio.Task[None]] = set()


@router.get("/status", summary="Live sync progress (SSE)")
async def stream_status(
    auth: AuthContext, account_id: Annotated[UUID, Query()]
) -> StreamingResponse:
    try:
        account = await service.get_account(auth.session, account_id)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account") from exc

    user_id = auth.user_id
    target = account.id

    async def events() -> AsyncIterator[str]:
        elapsed = 0.0
        last: str | None = None
        while elapsed < MAX_STREAM_SECONDS:
            payload = await _status_payload(user_id, target)
            encoded = payload.model_dump_json()
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
            if payload.phase in ("active", "error", "reauth_required", "idle"):
                break
            await asyncio.sleep(TICK_SECONDS)
            elapsed += TICK_SECONDS
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # nginx buffers SSE into uselessness without this.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/once", response_model=SyncStatus, summary="Sync progress, polled")
async def status_once(auth: AuthContext, account_id: Annotated[UUID, Query()]) -> SyncStatus:
    """For a client that cannot hold a stream open, and for tests."""
    try:
        account = await service.get_account(auth.session, account_id)
    except AccountNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account") from exc
    return await _status_payload(auth.user_id, account.id)


async def _status_payload(user_id: UUID, account_id: UUID) -> SyncStatus:
    progress = engine.progress_for(account_id)
    if progress is not None:
        return SyncStatus(
            account_id=account_id,
            phase=progress.phase,
            done=progress.done,
            total=progress.total,
            threads=progress.threads,
            new_messages=progress.new_messages,
            misses=progress.misses,
            error=progress.error,
        )

    # Nothing running in this process. The database still knows where the
    # last run got to, which is what makes the progress survive a restart.
    async with tenant_session(user_id) as session:
        from app.database.models.account import ConnectedAccount
        from app.modules.threads import store

        account = await session.get(ConnectedAccount, account_id)
        threads = await store.live_threads(session, account_id=account_id)
        return SyncStatus(
            account_id=account_id,
            phase="idle",
            done=account.initial_sync_done if account else 0,
            total=account.initial_sync_total if account else None,
            threads=threads,
            new_messages=0,
            misses=0,
            error=account.last_error if account else None,
        )
