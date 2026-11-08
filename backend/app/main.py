"""Application entrypoint.

Phase 0 mounts health only. Each later phase adds its own router here and
nowhere else, so the HTTP surface is readable in one screen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.v1 import (
    accounts,
    auth,
    companion,
    health,
    intelligence,
    memory,
    overview,
    runs,
    sync,
    tasks,
    threads,
)
from app.api.v1 import (
    settings as settings_routes,
)
from app.core.config import settings
from app.core.logging import bind_contextvars, clear_contextvars, configure_logging, get_logger
from app.database.engine import dispose_engine

log = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings.assert_production_ready()

    # Build the tool surface and the agent registry before serving. Schema
    # drift or a plane violation stops the process here rather than
    # surfacing the first time someone triggers that agent.
    from app.modules.mcp import bootstrap

    runtime = bootstrap.build()

    log.info(
        "startup",
        env=settings.env,
        version=__version__,
        tools=len(runtime.host.catalog.tools),
        agents=len(runtime.agents),
    )
    yield
    await dispose_engine()
    log.info("shutdown")


app = FastAPI(
    title="Maail API",
    version=__version__,
    summary="Thread-first email intelligence.",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER],
    max_age=600,
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Bind a request id to the log context and echo it back.

    Phase 5 binds ``run_id`` and ``agent`` to the same contextvars, which is
    what makes an agent run reconstructable from logs alone.
    """
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    clear_contextvars()
    bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request.failed")
        raise
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(threads.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(overview.router, prefix="/api/v1")
app.include_router(intelligence.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(companion.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(settings_routes.router, prefix="/api/v1")
