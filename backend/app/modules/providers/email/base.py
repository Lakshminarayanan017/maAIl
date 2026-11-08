"""What Maail needs from a mail provider.

Read-only. There is no send, no delete and no label write in this Protocol,
because v1 holds no scope that could perform one -- the contract and the
OAuth grant say the same thing, so neither can drift from the other quietly.

The DTOs are deliberately close to the wire. Normalisation is Tier 0's job in
``modules/ingest``; a provider that normalises is a provider whose bugs look
like parsing bugs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

__all__ = [
    "HistoryEvent",
    "HistoryPage",
    "MailProvider",
    "MessagePage",
    "MessageRef",
    "MessageUnavailable",
    "ProviderError",
    "RateLimited",
    "RawAttachment",
    "RawMessage",
    "StaleHistoryCursor",
]


class ProviderError(Exception):
    """The provider failed in a way the caller has to decide about."""


class RateLimited(ProviderError):
    """429 or a rate-limit 403. Retryable after a wait."""

    def __init__(self, message: str, *, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MessageUnavailable(ProviderError):
    """One message cannot be fetched. The batch continues (gap A7)."""


class StaleHistoryCursor(ProviderError):
    """The ``historyId`` is older than Gmail's retention, which is about a week.

    Not an error to retry: the cursor is gone for good, and the answer is a
    bounded reconciliation rather than a blind full resync (gap A2).
    """


@dataclass(frozen=True)
class MessageRef:
    provider_message_id: str
    provider_thread_id: str


@dataclass(frozen=True)
class MessagePage:
    refs: tuple[MessageRef, ...]
    next_page_token: str | None
    #: Gmail's own estimate. Good enough to drive a progress bar, not good
    #: enough to be called a total, which is why the UI shows it as one.
    size_estimate: int | None = None


@dataclass(frozen=True)
class RawAttachment:
    filename: str | None
    mime_type: str | None
    size_bytes: int | None
    provider_attachment_id: str | None


@dataclass(frozen=True)
class RawMessage:
    provider_message_id: str
    provider_thread_id: str
    label_ids: tuple[str, ...]
    snippet: str | None
    #: Gmail's internalDate, already converted. The Date header is parsed
    #: separately by ingest, because it carries the sender's offset.
    received_at: datetime
    size_bytes: int | None
    headers: dict[str, str]
    body_text: str | None = None
    body_html: str | None = None
    attachments: tuple[RawAttachment, ...] = ()
    #: False for a metadata-only fetch (pass 1).
    has_body: bool = False


HistoryKind = Literal["messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"]


@dataclass(frozen=True)
class HistoryEvent:
    kind: HistoryKind
    provider_message_id: str
    provider_thread_id: str | None = None
    label_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HistoryPage:
    events: tuple[HistoryEvent, ...] = ()
    next_page_token: str | None = None
    #: The cursor to store once the whole page set is applied.
    history_id: str | None = None
    labels_touched: Sequence[str] = field(default_factory=tuple)


class MailProvider(Protocol):
    """Read-only. Nothing here changes anything in the mailbox."""

    async def list_messages(
        self,
        *,
        page_token: str | None = ...,
        max_results: int = ...,
        after: datetime | None = ...,
        query: str | None = ...,
    ) -> MessagePage: ...

    async def get_metadata(self, provider_message_id: str) -> RawMessage: ...

    async def get_full(self, provider_message_id: str) -> RawMessage: ...

    async def list_history(
        self, *, start_history_id: str, page_token: str | None = ...
    ) -> HistoryPage: ...

    async def current_history_id(self) -> str: ...
