"""Envelope encryption: round trip, binding, tampering and rotation.

Gap D8. The rotation test is the one that matters most, because a scheme that
only ever round-trips under one key looks identical to one that cannot be
rotated at all -- right up to the morning you need to rotate it.
"""

from __future__ import annotations

import base64
import os
from uuid import uuid4

import pytest

from app.core.crypto import (
    CredentialDecryptionError,
    Keyring,
    SealedCredential,
    TokenPair,
    generate_key,
    open_tokens,
    seal_tokens,
)

TOKENS = TokenPair(access_token="ya29.access-token-value", refresh_token="1//refresh-token-value")


def keyring(*versions: int, active: int | None = None) -> Keyring:
    spec = ",".join(f"{v}:{base64.urlsafe_b64encode(bytes([v]) * 32).decode()}" for v in versions)
    return Keyring.parse(spec, active if active is not None else versions[0])


def test_round_trip() -> None:
    account_id = uuid4()
    ring = keyring(1)
    sealed = seal_tokens(account_id, TOKENS, keyring=ring)
    assert open_tokens(account_id, sealed, keyring=ring) == TOKENS


def test_nothing_recognisable_survives_into_the_ciphertext() -> None:
    sealed = seal_tokens(uuid4(), TOKENS, keyring=keyring(1))
    blob = sealed.access_ciphertext + sealed.refresh_ciphertext + sealed.dek_wrapped
    assert b"ya29" not in blob
    assert b"1//" not in blob
    assert TOKENS.access_token.encode() not in blob


def test_two_seals_of_the_same_token_differ() -> None:
    """A fresh data key and a fresh nonce each time.

    Identical ciphertext for identical input would let anyone with read
    access tell that two accounts share a token.
    """
    ring = keyring(1)
    account_id = uuid4()
    first = seal_tokens(account_id, TOKENS, keyring=ring)
    second = seal_tokens(account_id, TOKENS, keyring=ring)
    assert first.access_ciphertext != second.access_ciphertext
    assert first.dek_wrapped != second.dek_wrapped


def test_ciphertext_cannot_be_moved_to_another_account() -> None:
    """The account id is additional authenticated data.

    Without it, someone with database write access could paste their own
    credential row into your account and have Maail sync their mailbox as
    you -- or, worse, paste yours into theirs.
    """
    ring = keyring(1)
    mine, theirs = uuid4(), uuid4()
    sealed = seal_tokens(mine, TOKENS, keyring=ring)

    with pytest.raises(CredentialDecryptionError):
        open_tokens(theirs, sealed, keyring=ring)


def test_a_flipped_bit_is_detected() -> None:
    ring = keyring(1)
    account_id = uuid4()
    sealed = seal_tokens(account_id, TOKENS, keyring=ring)

    corrupted = bytearray(sealed.access_ciphertext)
    corrupted[-1] ^= 0x01
    tampered = SealedCredential(
        access_ciphertext=bytes(corrupted),
        refresh_ciphertext=sealed.refresh_ciphertext,
        dek_wrapped=sealed.dek_wrapped,
        key_version=sealed.key_version,
    )

    with pytest.raises(CredentialDecryptionError):
        open_tokens(account_id, tampered, keyring=ring)


def test_a_truncated_ciphertext_is_refused_rather_than_crashing() -> None:
    ring = keyring(1)
    account_id = uuid4()
    sealed = seal_tokens(account_id, TOKENS, keyring=ring)
    stub = SealedCredential(
        access_ciphertext=b"short",
        refresh_ciphertext=sealed.refresh_ciphertext,
        dek_wrapped=sealed.dek_wrapped,
        key_version=sealed.key_version,
    )
    with pytest.raises(CredentialDecryptionError, match="too short"):
        open_tokens(account_id, stub, keyring=ring)


class TestRotation:
    """Adding a key must not strand the rows written under the old one."""

    def test_a_row_sealed_under_v1_still_opens_once_v2_is_active(self) -> None:
        account_id = uuid4()
        old = keyring(1, 2, active=1)
        sealed = seal_tokens(account_id, TOKENS, keyring=old)
        assert sealed.key_version == 1

        rotated = keyring(1, 2, active=2)
        assert open_tokens(account_id, sealed, keyring=rotated) == TOKENS

    def test_new_rows_use_the_active_key(self) -> None:
        rotated = keyring(1, 2, active=2)
        sealed = seal_tokens(uuid4(), TOKENS, keyring=rotated)
        assert sealed.key_version == 2

    def test_is_current_identifies_what_still_needs_rewrapping(self) -> None:
        rotated = keyring(1, 2, active=2)
        assert rotated.is_current(2) is True
        assert rotated.is_current(1) is False

    def test_retiring_a_key_that_rows_still_use_fails_loudly(self) -> None:
        account_id = uuid4()
        sealed = seal_tokens(account_id, TOKENS, keyring=keyring(1, 2, active=1))

        only_v2 = keyring(2)
        with pytest.raises(CredentialDecryptionError, match="no key loaded for version 1"):
            open_tokens(account_id, sealed, keyring=only_v2)


class TestKeyringParsing:
    def test_rejects_a_key_of_the_wrong_length(self) -> None:
        short = base64.urlsafe_b64encode(os.urandom(16)).decode()
        with pytest.raises(ValueError, match="must be 32 bytes"):
            Keyring.parse(f"1:{short}", 1)

    def test_rejects_an_active_version_it_does_not_hold(self) -> None:
        with pytest.raises(ValueError, match="only versions"):
            Keyring.parse(f"1:{generate_key()}", 2)

    def test_rejects_an_empty_specification(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Keyring.parse("", 1)

    def test_rejects_an_entry_without_a_version(self) -> None:
        with pytest.raises(ValueError, match="<version>:<base64 key>"):
            Keyring.parse(generate_key(), 1)

    def test_generated_keys_are_usable(self) -> None:
        ring = Keyring.parse(f"7:{generate_key()}", 7)
        account_id = uuid4()
        assert (
            open_tokens(account_id, seal_tokens(account_id, TOKENS, keyring=ring), keyring=ring)
            == TOKENS
        )
