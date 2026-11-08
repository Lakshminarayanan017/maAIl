"""PKCE (RFC 7636) and the state nonce.

Small enough to read in one sitting, which is the point: an authorization
flow's randomness should not live inside a larger file where it can be
quietly weakened.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

#: RFC 7636 allows 43-128 characters. 64 bytes of entropy lands at 86.
_VERIFIER_BYTES = 64
_STATE_BYTES = 32


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_verifier() -> str:
    """The secret half of the exchange. Never leaves this browser session."""
    return _b64url(secrets.token_bytes(_VERIFIER_BYTES))


def verifier_challenge(verifier: str) -> str:
    """S256, the only method worth using. ``plain`` defeats the purpose."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state() -> str:
    """CSRF protection for the redirect. Single use, checked at callback."""
    return _b64url(secrets.token_bytes(_STATE_BYTES))
