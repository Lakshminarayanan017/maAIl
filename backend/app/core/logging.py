"""Structured logging, run_id-aware.

Every log line carries whatever is bound to the context: ``request_id`` always,
``user_id`` once a request is authenticated, ``run_id`` and ``agent`` once an
agent run starts. Traces in phase 5 bind to the same contextvars, so a run can
be reconstructed from logs alone.

One rule enforced by a test: raw email content never reaches a log line. See
``REDACT_KEYS``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars
from structlog.typing import EventDict, WrappedLogger

from app.core.config import settings

__all__ = [
    "REDACT_KEYS",
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "get_logger",
    "unbind_contextvars",
]

#: Keys whose values are never emitted. Plane U content and credentials.
REDACT_KEYS: frozenset[str] = frozenset(
    {
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set-cookie",
        "password",
        "session_secret",
        "client_secret",
        "body_html",
        "body_text",
        "body_text_stripped",
        "snippet",
        "subject",
        "attachment_text",
        "prompt",
        "completion",
    }
)

_REDACTED = "[redacted]"


def _redact(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        if key.lower() in REDACT_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging() -> None:
    # structlog.stdlib.* processors require a stdlib logger underneath.
    # The factory here is PrintLogger, so the plain processors are the right
    # ones; add_logger_name in particular would reach for `logger.name` and
    # fail at the first log line, which is exactly how this was found.
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        _redact,
    ]

    if settings.is_production:
        processors += [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors += [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Cached outside production only. A cached bound logger freezes the
        # processor chain it was created with, which makes the configuration
        # impossible to change afterwards -- including from a test that wants
        # to read what was logged.
        cache_logger_on_first_use=settings.is_production,
    )

    logging.basicConfig(level=settings.log_level, stream=sys.stderr, format="%(message)s")
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True


def get_logger(name: str | None = None) -> Any:
    """A logger that carries its module name as a bound field.

    Bound rather than derived from the underlying logger, because the
    underlying logger is a PrintLogger and has no name to derive.
    """
    logger = structlog.get_logger()
    return logger.bind(logger=name) if name else logger
