"""The Gmail REST client. Read-only, quota-aware, failure-tolerant.

Three things here are not obvious and are the reason this file exists rather
than a thin wrapper over `googleapiclient`:

**Quota is per minute.** Every call spends through the account's token bucket
before it is made. The alternative is finding the limit by hitting it, which
costs a 429, a backoff and a retry for the same work.

**A 404 on `history.list` is not a failure**, it is a cursor older than
Gmail's roughly one-week retention. It raises ``StaleHistoryCursor`` so the
caller reconciles instead of resyncing a mailbox.

**A 404 on one message is not a failure either.** Messages get deleted
between the list call and the get call, every single sync. It raises
``MessageUnavailable``, the batch records a miss and continues (gap A7).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.core.logging import get_logger
from app.modules.providers.email.base import (
    HistoryEvent,
    HistoryKind,
    HistoryPage,
    MessagePage,
    MessageRef,
    MessageUnavailable,
    ProviderError,
    RateLimited,
    RawAttachment,
    RawMessage,
    StaleHistoryCursor,
)
from app.modules.sync.quota import (
    UNITS_GET_FULL,
    UNITS_GET_METADATA,
    UNITS_HISTORY_LIST,
    UNITS_LIST,
    UNITS_PROFILE,
    QuotaLimiter,
)
from app.modules.sync.quota import (
    limiter as default_limiter,
)

log = get_logger(__name__)

API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"

#: Only what ingest actually reads. Asking for fewer headers is a smaller
#: response on every one of tens of thousands of messages.
METADATA_HEADERS = (
    "From",
    "To",
    "Cc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
    "List-Unsubscribe",
)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

#: Gmail history event names, in the order the sync applies them.
_HISTORY_KINDS: tuple[HistoryKind, ...] = (
    "messagesAdded",
    "messagesDeleted",
    "labelsAdded",
    "labelsRemoved",
)


class GmailClient:
    """One client per account per sync run."""

    def __init__(
        self,
        *,
        account_id: UUID,
        access_token: str,
        http: httpx.AsyncClient | None = None,
        quota: QuotaLimiter | None = None,
    ) -> None:
        self._account_id = account_id
        self._token = access_token
        self._http = http
        self._quota = quota or default_limiter

    # -- calls -------------------------------------------------------------
    async def list_messages(
        self,
        *,
        page_token: str | None = None,
        max_results: int = 500,
        after: datetime | None = None,
        query: str | None = None,
    ) -> MessagePage:
        params: dict[str, Any] = {"maxResults": max_results, "includeSpamTrash": "false"}
        if page_token:
            params["pageToken"] = page_token

        clauses = [query] if query else []
        if after is not None:
            # Gmail's `after:` takes a date, not an instant, and is
            # inclusive. A day of overlap is cheap; a missed message is not.
            clauses.append(f"after:{after.strftime('%Y/%m/%d')}")
        if clauses:
            params["q"] = " ".join(clauses)

        data = await self._get("/messages", params, units=UNITS_LIST, what="messages.list")
        raw = data.get("messages") or []
        return MessagePage(
            refs=tuple(
                MessageRef(
                    provider_message_id=str(item["id"]),
                    provider_thread_id=str(item.get("threadId") or item["id"]),
                )
                for item in raw
                if item.get("id")
            ),
            next_page_token=data.get("nextPageToken"),
            size_estimate=data.get("resultSizeEstimate"),
        )

    async def get_metadata(self, provider_message_id: str) -> RawMessage:
        """Pass 1. Headers and labels, no body: 20 units instead of 60."""
        params: dict[str, Any] = {
            "format": "metadata",
            "metadataHeaders": list(METADATA_HEADERS),
        }
        data = await self._get(
            f"/messages/{provider_message_id}",
            params,
            units=UNITS_GET_METADATA,
            what="messages.get:metadata",
            message_id=provider_message_id,
        )
        return self._to_message(data, with_body=False)

    async def get_full(self, provider_message_id: str) -> RawMessage:
        """Pass 2. The whole payload, at three times the price."""
        data = await self._get(
            f"/messages/{provider_message_id}",
            {"format": "full"},
            units=UNITS_GET_FULL,
            what="messages.get:full",
            message_id=provider_message_id,
        )
        return self._to_message(data, with_body=True)

    async def list_history(
        self, *, start_history_id: str, page_token: str | None = None
    ) -> HistoryPage:
        params: dict[str, Any] = {"startHistoryId": start_history_id, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token

        try:
            data = await self._get(
                "/history", params, units=UNITS_HISTORY_LIST, what="history.list"
            )
        except MessageUnavailable as exc:
            # Gmail answers 404 for a historyId it has aged out. Retention is
            # guaranteed for about a week, so this is expected, not broken.
            raise StaleHistoryCursor(str(exc)) from exc

        events: list[HistoryEvent] = []
        for record in data.get("history") or []:
            for kind in _HISTORY_KINDS:
                for entry in record.get(kind) or []:
                    message = entry.get("message") or {}
                    identifier = message.get("id")
                    if not identifier:
                        continue
                    events.append(
                        HistoryEvent(
                            kind=kind,
                            provider_message_id=str(identifier),
                            provider_thread_id=(
                                str(message["threadId"]) if message.get("threadId") else None
                            ),
                            label_ids=tuple(entry.get("labelIds") or message.get("labelIds") or ()),
                        )
                    )

        return HistoryPage(
            events=tuple(events),
            next_page_token=data.get("nextPageToken"),
            history_id=str(data["historyId"]) if data.get("historyId") else None,
        )

    async def current_history_id(self) -> str:
        data = await self._get("/profile", {}, units=UNITS_PROFILE, what="getProfile")
        history_id = data.get("historyId")
        if not history_id:
            raise ProviderError("Gmail returned a profile with no historyId")
        return str(history_id)

    # -- plumbing ----------------------------------------------------------
    async def _get(
        self,
        path: str,
        params: dict[str, Any],
        *,
        units: int,
        what: str,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        await self._quota.spend(self._account_id, units, what=what)

        try:
            if self._http is not None:
                response = await self._http.get(
                    f"{API_ROOT}{path}", params=params, headers=self._headers()
                )
            else:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    response = await client.get(
                        f"{API_ROOT}{path}", params=params, headers=self._headers()
                    )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Gmail: {exc}") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise MessageUnavailable(f"Gmail has no {message_id or path}")
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise RateLimited("Gmail rate limit", retry_after=_retry_after(response))
        if response.status_code == httpx.codes.FORBIDDEN:
            reason = _error_reason(response)
            if reason in ("rateLimitExceeded", "userRateLimitExceeded"):
                # The bucket is meant to prevent this. Reaching it means the
                # unit prices are wrong, so it is worth a loud log line.
                log.warning("gmail.rate_limited_despite_bucket", reason=reason, call=what)
                raise RateLimited(reason, retry_after=_retry_after(response))
            raise ProviderError(f"Gmail refused the request: {reason or 'forbidden'}")
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise ProviderError("Gmail rejected the access token")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProviderError(f"Gmail returned {response.status_code} for {what}")

        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    # -- payload -----------------------------------------------------------
    def _to_message(self, data: dict[str, Any], *, with_body: bool) -> RawMessage:
        payload = data.get("payload") or {}
        headers = {
            str(h.get("name", "")).strip(): str(h.get("value", ""))
            for h in payload.get("headers") or []
            if h.get("name")
        }

        received_at = datetime.fromtimestamp(
            int(data.get("internalDate", 0)) / 1000, tz=timezone.utc
        )

        body_text: str | None = None
        body_html: str | None = None
        attachments: tuple[RawAttachment, ...] = ()
        if with_body:
            body_text, body_html, attachments = _walk(payload)

        return RawMessage(
            provider_message_id=str(data["id"]),
            provider_thread_id=str(data.get("threadId") or data["id"]),
            label_ids=tuple(data.get("labelIds") or ()),
            snippet=data.get("snippet"),
            received_at=received_at,
            size_bytes=data.get("sizeEstimate"),
            headers=headers,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            has_body=with_body,
        )


def _walk(payload: dict[str, Any]) -> tuple[str | None, str | None, tuple[RawAttachment, ...]]:
    """Depth-first over the MIME tree, collecting the first of each kind.

    The first text/plain wins over later ones, because a multipart/alternative
    lists the plain part first and anything after it in a nested part is
    usually a quoted footer rather than the message.
    """
    text: str | None = None
    html: str | None = None
    attachments: list[RawAttachment] = []

    stack: list[dict[str, Any]] = [payload]
    while stack:
        part = stack.pop(0)
        mime = str(part.get("mimeType") or "")
        body = part.get("body") or {}
        filename = part.get("filename") or ""

        if filename:
            attachments.append(
                RawAttachment(
                    filename=filename,
                    mime_type=mime or None,
                    size_bytes=body.get("size"),
                    provider_attachment_id=body.get("attachmentId"),
                )
            )
        elif mime == "text/plain" and text is None:
            text = _decode(body.get("data"))
        elif mime == "text/html" and html is None:
            html = _decode(body.get("data"))

        stack.extend(part.get("parts") or [])

    return text, html, tuple(attachments)


def _decode(data: str | None) -> str | None:
    if not data:
        return None
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
            "utf-8", errors="replace"
        )
    except (binascii.Error, ValueError):
        # A body that will not decode is a body we do not have. The message
        # still exists and its headers are still useful.
        return None


def _error_reason(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    errors = (body.get("error") or {}).get("errors") or []
    if errors and isinstance(errors, list):
        return str(errors[0].get("reason")) or None
    return None


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    try:
        return max(1.0, float(raw)) if raw else 2.0
    except ValueError:
        return 2.0
