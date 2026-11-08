"""Plane U content and credentials never reach a log line."""

from __future__ import annotations

from app.core.logging import REDACT_KEYS, _redact


def test_credentials_and_email_bodies_are_redacted() -> None:
    event = {
        "event": "thread.ingested",
        "thread_id": "t_1",
        "subject": "Re: offer letter",
        "body_text_stripped": "Dear Nishanth, please sign by Friday",
        "refresh_token": "1//0gLm",
        "Authorization": "Bearer abc",
    }
    out = _redact(None, "info", dict(event))

    assert out["thread_id"] == "t_1"
    assert out["subject"] == "[redacted]"
    assert out["body_text_stripped"] == "[redacted]"
    assert out["refresh_token"] == "[redacted]"
    assert out["Authorization"] == "[redacted]", "header casing must not defeat redaction"


def test_the_redaction_list_covers_every_plane_u_body_field() -> None:
    for field in ("body_html", "body_text", "body_text_stripped", "snippet", "attachment_text"):
        assert field in REDACT_KEYS


def test_configure_logging_produces_a_working_logger() -> None:
    """The configuration has to survive contact with a log call.

    Processors and the logger factory have to agree: a stdlib processor over
    a PrintLogger raises on the first line, and nothing before this test
    exercised the pairing, because the ASGI tests never run the lifespan.
    """
    import structlog

    from app.core.logging import configure_logging, get_logger

    original = structlog.get_config()
    try:
        configure_logging()
        log = get_logger("tests.logging")
        log.info("startup", env="test", version="0.1.0")
        log.warning("something", account_id="abc", refresh_token="secret")
    finally:
        structlog.configure(**original)


def test_a_configured_logger_still_redacts() -> None:
    import structlog

    from app.core.logging import configure_logging, get_logger

    captured: list[dict[str, object]] = []

    original = structlog.get_config()
    try:
        configure_logging()
        processors = structlog.get_config()["processors"]
        structlog.configure(
            processors=[*processors[:-1], lambda _l, _n, ed: captured.append(dict(ed)) or ""]
        )
        get_logger("tests.logging").info("token.seen", refresh_token="1//super-secret")
    finally:
        structlog.configure(**original)

    assert captured
    assert captured[0]["refresh_token"] == "[redacted]"
    assert "1//super-secret" not in repr(captured)
