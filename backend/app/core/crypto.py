"""Envelope encryption for provider credentials, with a rotatable key version.

Gap D8. A stored OAuth token encrypted under a key that can never be rotated
is a token you can never rotate, so the scheme is two-level from the start:

    DEK   a fresh 256-bit data key per credential row, encrypting the tokens
    KEK   a long-lived key encryption key from the environment, wrapping the DEK

``oauth_credentials.key_version`` records which KEK wrapped that row's DEK.
Rotation adds a new KEK, flips the active version, and re-wraps rows in the
background; the old KEK stays readable until the last row has moved. Nothing
has to be decrypted and re-encrypted wholesale, because only the DEK is
wrapped by the KEK.

Both layers are AES-256-GCM, and both bind the account id as additional
authenticated data. Without that, ciphertext from one row could be pasted into
another and would decrypt cleanly -- an attacker with write access to the
database could point your credentials at their account.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

NONCE_BYTES = 12
KEY_BYTES = 32

__all__ = [
    "CredentialDecryptionError",
    "Keyring",
    "SealedCredential",
    "TokenPair",
    "get_keyring",
    "open_tokens",
    "seal_tokens",
]


class CredentialDecryptionError(Exception):
    """The ciphertext did not authenticate under the key it claims.

    Raised for a wrong key version, a tampered row, or a ciphertext moved
    between accounts. Never carries the key, the account or the plaintext.
    """


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class SealedCredential:
    access_ciphertext: bytes
    refresh_ciphertext: bytes
    dek_wrapped: bytes
    key_version: int
    access_expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None


def _decode_key(raw: str) -> bytes:
    """Accept base64 or base64url, with or without padding."""
    candidate = raw.strip()
    padding = "=" * (-len(candidate) % 4)
    try:
        key = base64.urlsafe_b64decode(candidate + padding)
    except Exception as exc:
        raise ValueError("encryption key is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise ValueError(f"encryption key must be {KEY_BYTES} bytes, got {len(key)}")
    return key


class Keyring:
    """The key encryption keys, by version.

    Parsed from ``DATA_ENCRYPTION_KEYS`` as ``1:<base64>,2:<base64>``. The
    active version is ``DATA_ENCRYPTION_KEY_VERSION``; every other version
    stays loaded so rows encrypted under it remain readable while they are
    re-wrapped.
    """

    def __init__(self, keys: dict[int, bytes], active: int) -> None:
        if not keys:
            raise ValueError("DATA_ENCRYPTION_KEYS is empty")
        if active not in keys:
            raise ValueError(
                f"DATA_ENCRYPTION_KEY_VERSION is {active}, "
                f"but only versions {sorted(keys)} are loaded"
            )
        self._keys = keys
        self._active = active

    @classmethod
    def parse(cls, spec: str, active: int) -> Keyring:
        keys: dict[int, bytes] = {}
        for entry in spec.split(","):
            entry = entry.strip()
            if not entry:
                continue
            version, _, material = entry.partition(":")
            if not material:
                raise ValueError("DATA_ENCRYPTION_KEYS entries must be '<version>:<base64 key>'")
            try:
                parsed_version = int(version)
            except ValueError as exc:
                raise ValueError("DATA_ENCRYPTION_KEYS version must be an integer") from exc
            keys[parsed_version] = _decode_key(material)
        return cls(keys, active)

    @property
    def active_version(self) -> int:
        return self._active

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._keys))

    def wrap(self, dek: bytes, aad: bytes) -> tuple[bytes, int]:
        return _encrypt(self._keys[self._active], dek, aad), self._active

    def unwrap(self, wrapped: bytes, version: int, aad: bytes) -> bytes:
        key = self._keys.get(version)
        if key is None:
            raise CredentialDecryptionError(
                f"no key loaded for version {version}; loaded versions are {list(self.versions)}"
            )
        return _decrypt(key, wrapped, aad)

    def is_current(self, version: int) -> bool:
        """False for a row that rotation still has to re-wrap."""
        return version == self._active


def _encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) <= NONCE_BYTES:
        raise CredentialDecryptionError("ciphertext is too short to contain a nonce")
    nonce, body = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    try:
        return AESGCM(key).decrypt(nonce, body, aad)
    except InvalidTag as exc:
        raise CredentialDecryptionError(
            "ciphertext failed authentication: wrong key, tampered row, "
            "or a value moved between accounts"
        ) from exc


@lru_cache(maxsize=1)
def get_keyring() -> Keyring:
    return Keyring.parse(settings.data_encryption_keys, settings.data_encryption_key_version)


def _aad(account_id: UUID) -> bytes:
    """Binds a ciphertext to the row it belongs to."""
    return b"maail:oauth_credentials:" + str(account_id).encode("ascii")


def seal_tokens(
    account_id: UUID,
    tokens: TokenPair,
    *,
    access_expires_at: datetime | None = None,
    refresh_expires_at: datetime | None = None,
    keyring: Keyring | None = None,
) -> SealedCredential:
    """Encrypt a token pair under a fresh data key."""
    ring = keyring or get_keyring()
    aad = _aad(account_id)
    dek = os.urandom(KEY_BYTES)
    wrapped, version = ring.wrap(dek, aad)
    return SealedCredential(
        access_ciphertext=_encrypt(dek, tokens.access_token.encode("utf-8"), aad),
        refresh_ciphertext=_encrypt(dek, tokens.refresh_token.encode("utf-8"), aad),
        dek_wrapped=wrapped,
        key_version=version,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def open_tokens(
    account_id: UUID,
    sealed: SealedCredential,
    *,
    keyring: Keyring | None = None,
) -> TokenPair:
    """Decrypt a token pair. The only way a token re-enters memory."""
    ring = keyring or get_keyring()
    aad = _aad(account_id)
    dek = ring.unwrap(sealed.dek_wrapped, sealed.key_version, aad)
    return TokenPair(
        access_token=_decrypt(dek, sealed.access_ciphertext, aad).decode("utf-8"),
        refresh_token=_decrypt(dek, sealed.refresh_ciphertext, aad).decode("utf-8"),
    )


def generate_key() -> str:
    """A new KEK, base64url, for an operator to paste into the environment."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


if __name__ == "__main__":  # pragma: no cover - an operator convenience
    import sys

    sys.stdout.write(generate_key() + "\n")
