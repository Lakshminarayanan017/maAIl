"""What Maail needs from an OAuth provider, and nothing more.

A Protocol rather than a base class, so a fake in a test is a small class
rather than an inheritance chain, and so the Gmail-specific parts stay in the
Gmail implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

__all__ = [
    "AuthorizationRequest",
    "OAuthClient",
    "OAuthError",
    "ReauthRequired",
    "TokenGrant",
    "UserIdentity",
]


class OAuthError(Exception):
    """The provider refused, and retrying the same way will not help."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ReauthRequired(OAuthError):
    """The refresh token is dead; only the user can fix this.

    Google answers ``invalid_grant`` when a Testing-mode refresh token has
    aged out, when the user revoked access, or when the grant was pushed out
    by the hundred-token-per-client limit. All three need the same thing: the
    person to authorise again. So they get one exception, and the account
    moves to ``reauth_required`` rather than ``error`` (gap A3).
    """


@dataclass(frozen=True)
class AuthorizationRequest:
    authorize_url: str
    state: str
    code_verifier: str


@dataclass(frozen=True)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    granted_scopes: tuple[str, ...]
    access_expires_at: datetime
    #: Known in advance only while the OAuth app is in Testing mode, where
    #: Google expires the refresh token after about a week (gap A3).
    refresh_expires_at: datetime | None = None
    raw_scope: str = ""


@dataclass(frozen=True)
class UserIdentity:
    email: str
    name: str | None = None
    provider_subject: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


class OAuthClient(Protocol):
    """Read-only by construction: nothing here sends mail or changes a label."""

    @property
    def required_scopes(self) -> frozenset[str]: ...

    def build_authorization_request(
        self, *, prompt_consent: bool = ..., login_hint: str | None = ...
    ) -> AuthorizationRequest: ...

    async def exchange_code(self, *, code: str, code_verifier: str) -> TokenGrant: ...

    async def refresh(self, *, refresh_token: str) -> TokenGrant: ...

    async def fetch_identity(self, *, access_token: str) -> UserIdentity: ...

    async def revoke(self, *, token: str) -> bool: ...
