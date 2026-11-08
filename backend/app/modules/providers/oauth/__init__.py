"""OAuth clients.

The contract is in ``base.py``. Agents never import this package; it is an
outbound integration and it reaches them, if at all, through ``mcp``.
"""

from app.modules.providers.oauth.base import (
    AuthorizationRequest,
    OAuthClient,
    OAuthError,
    ReauthRequired,
    TokenGrant,
    UserIdentity,
)

__all__ = [
    "AuthorizationRequest",
    "OAuthClient",
    "OAuthError",
    "ReauthRequired",
    "TokenGrant",
    "UserIdentity",
]
