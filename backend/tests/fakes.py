"""Stand-ins for the things a test must not actually call.

The fake OAuth client is a real implementation of the Protocol in
``providers/oauth/base.py``, not a mock with recorded calls. It can be told to
fail the way Google fails -- ``invalid_grant`` on a dead refresh token, a
narrowed scope set when someone unticks a box -- so the tests exercise the
paths that matter rather than the happy one twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.core.clock import get_clock
from app.modules.providers.oauth.base import (
    AuthorizationRequest,
    OAuthError,
    ReauthRequired,
    TokenGrant,
    UserIdentity,
)
from app.modules.providers.oauth.google import REQUESTED_SCOPES
from app.modules.providers.oauth.pkce import new_state, new_verifier, verifier_challenge


@dataclass
class FakeOAuthClient:
    """A Google that does what the test says."""

    email: str = "person@example.com"
    name: str | None = "A Person"
    granted_scopes: tuple[str, ...] = REQUESTED_SCOPES
    access_token: str = "fake-access-token-aaaa"
    refresh_token: str = "fake-refresh-token-bbbb"
    access_ttl_seconds: int = 3600
    refresh_ttl_days: int | None = 7

    #: Flip these to make Google misbehave.
    refresh_fails_with_invalid_grant: bool = False
    exchange_returns_no_refresh_token: bool = False
    revoke_succeeds: bool = True

    issued: list[AuthorizationRequest] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    refresh_calls: int = 0

    @property
    def required_scopes(self) -> frozenset[str]:
        from app.modules.providers.oauth.google import REQUIRED_SCOPES

        return REQUIRED_SCOPES

    def build_authorization_request(
        self, *, prompt_consent: bool = True, login_hint: str | None = None
    ) -> AuthorizationRequest:
        verifier = new_verifier()
        state = new_state()
        request = AuthorizationRequest(
            authorize_url=(
                "https://accounts.google.test/authorize"
                f"?state={state}&code_challenge={verifier_challenge(verifier)}"
                f"&login_hint={login_hint or ''}&prompt={'consent' if prompt_consent else ''}"
            ),
            state=state,
            code_verifier=verifier,
        )
        self.issued.append(request)
        return request

    async def exchange_code(self, *, code: str, code_verifier: str) -> TokenGrant:
        if not code:
            raise OAuthError("no code")
        if self.exchange_returns_no_refresh_token:
            raise OAuthError("Google returned no refresh token", code="no_refresh_token")
        return self._grant(fresh_refresh=True)

    async def refresh(self, *, refresh_token: str) -> TokenGrant:
        self.refresh_calls += 1
        if self.refresh_fails_with_invalid_grant:
            # What a Testing-mode token looks like on day eight (gap A3).
            raise ReauthRequired("Google refused to renew", code="invalid_grant")
        return self._grant(fresh_refresh=False)

    async def fetch_identity(self, *, access_token: str) -> UserIdentity:
        return UserIdentity(email=self.email, name=self.name, provider_subject="sub-1")

    async def revoke(self, *, token: str) -> bool:
        self.revoked.append(token)
        return self.revoke_succeeds

    def _grant(self, *, fresh_refresh: bool) -> TokenGrant:
        now = get_clock().now()
        refresh_expires_at = None
        if fresh_refresh and self.refresh_ttl_days is not None:
            refresh_expires_at = now + timedelta(days=self.refresh_ttl_days)
        return TokenGrant(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            granted_scopes=tuple(self.granted_scopes),
            access_expires_at=now + timedelta(seconds=self.access_ttl_seconds),
            refresh_expires_at=refresh_expires_at,
            raw_scope=" ".join(self.granted_scopes),
        )


# ---------------------------------------------------------------------------
# a Gmail that does what the test says
# ---------------------------------------------------------------------------
@dataclass
class FakeMessage:
    """One message as Gmail would hand it over."""

    message_id: str
    thread_id: str
    subject: str = "Hello"
    sender: str = "them@example.com"
    to: str = "person@example.com"
    sent: str = "Tue, 10 Mar 2026 09:00:00 +0000"
    rfc822: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    body: str = "The body."
    labels: tuple[str, ...] = ("INBOX", "UNREAD")

    def payload(self, *, with_body: bool) -> dict[str, object]:
        headers = [
            {"name": "From", "value": self.sender},
            {"name": "To", "value": self.to},
            {"name": "Subject", "value": self.subject},
            {"name": "Date", "value": self.sent},
        ]
        if self.rfc822:
            headers.append({"name": "Message-ID", "value": self.rfc822})
        if self.in_reply_to:
            headers.append({"name": "In-Reply-To", "value": self.in_reply_to})
        if self.references:
            headers.append({"name": "References", "value": self.references})

        payload: dict[str, object] = {"headers": headers, "mimeType": "text/plain"}
        if with_body:
            import base64

            payload["body"] = {
                "data": base64.urlsafe_b64encode(self.body.encode()).decode().rstrip("=")
            }
        return payload


class FakeGmail:
    """A mailbox, a quota counter, and whatever failures a test asks for.

    Counts calls so the quota gate can assert that a sync never asks for
    more units than a minute allows, and can be told to raise
    ``StaleHistoryCursor`` so the reconciliation gate has something to
    recover from.
    """

    def __init__(
        self,
        messages: list[FakeMessage],
        *,
        history_id: str = "1000",
        stale_cursor: bool = False,
        missing: set[str] | None = None,
    ) -> None:
        self.messages = {m.message_id: m for m in messages}
        self.history_id = history_id
        self.stale_cursor = stale_cursor
        self.missing = missing or set()
        self.units_spent = 0
        self.calls: list[str] = []
        self.history_events: list[object] = []

    # -- the MailProvider surface -----------------------------------------
    async def list_messages(
        self,
        *,
        page_token: str | None = None,
        max_results: int = 500,
        after: object | None = None,
        query: str | None = None,
    ) -> object:
        from app.modules.providers.email.base import MessagePage, MessageRef
        from app.modules.sync.quota import UNITS_LIST

        self._spend(UNITS_LIST, "messages.list")
        refs = tuple(
            MessageRef(provider_message_id=m.message_id, provider_thread_id=m.thread_id)
            for m in self.messages.values()
        )
        return MessagePage(refs=refs, next_page_token=None, size_estimate=len(refs))

    async def get_metadata(self, provider_message_id: str) -> object:
        from app.modules.sync.quota import UNITS_GET_METADATA

        self._spend(UNITS_GET_METADATA, "messages.get:metadata")
        return self._build(provider_message_id, with_body=False)

    async def get_full(self, provider_message_id: str) -> object:
        from app.modules.sync.quota import UNITS_GET_FULL

        self._spend(UNITS_GET_FULL, "messages.get:full")
        return self._build(provider_message_id, with_body=True)

    async def list_history(self, *, start_history_id: str, page_token: str | None = None) -> object:
        from app.modules.providers.email.base import HistoryPage, StaleHistoryCursor
        from app.modules.sync.quota import UNITS_HISTORY_LIST

        self._spend(UNITS_HISTORY_LIST, "history.list")
        if self.stale_cursor:
            raise StaleHistoryCursor("historyId is too old")
        return HistoryPage(
            events=tuple(self.history_events),  # type: ignore[arg-type]
            next_page_token=None,
            history_id=self.history_id,
        )

    async def current_history_id(self) -> str:
        from app.modules.sync.quota import UNITS_PROFILE

        self._spend(UNITS_PROFILE, "getProfile")
        return self.history_id

    # -- helpers ------------------------------------------------------------
    def _spend(self, units: int, what: str) -> None:
        self.units_spent += units
        self.calls.append(what)

    def _build(self, provider_message_id: str, *, with_body: bool) -> object:
        from app.modules.providers.email.base import MessageUnavailable

        if provider_message_id in self.missing:
            raise MessageUnavailable(provider_message_id)
        message = self.messages.get(provider_message_id)
        if message is None:
            raise MessageUnavailable(provider_message_id)

        from app.modules.providers.email.gmail import GmailClient

        client = GmailClient.__new__(GmailClient)
        return client._to_message(
            {
                "id": message.message_id,
                "threadId": message.thread_id,
                "labelIds": list(message.labels),
                "snippet": message.body[:50],
                "internalDate": "1772528400000",
                "sizeEstimate": len(message.body),
                "payload": message.payload(with_body=with_body),
            },
            with_body=with_body,
        )

    def factory(self):
        def build(_access_token: str) -> FakeGmail:
            return self

        return build
