"""Phase 1 blocking gate: no plaintext token in the database or logs.

Rather than inspecting the one column we expect to be encrypted, this sweeps
**every** text and bytea column in the public schema for the token values.
A token that leaks does not usually leak where you were looking -- it ends up
in a ``last_error``, a debug column someone added, or a log line.
"""

from __future__ import annotations

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.helpers import sign_in

pytestmark = [pytest.mark.security, pytest.mark.integration]

_SCANNABLE_COLUMNS = text(
    """
    SELECT c.table_name, c.column_name, c.data_type
    FROM information_schema.columns c
    JOIN pg_class t ON t.relname = c.table_name
    JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'
    WHERE c.table_schema = 'public'
      AND t.relkind = 'r'
      AND c.data_type IN ('text', 'character varying', 'bytea', 'ARRAY', 'USER-DEFINED')
    ORDER BY c.table_name, c.column_name
    """
)


async def test_no_column_anywhere_contains_a_token(
    api: object, owner_engine: AsyncEngine, fake_oauth: object
) -> None:
    await sign_in(api)

    access = fake_oauth.access_token  # type: ignore[attr-defined]
    refresh = fake_oauth.refresh_token  # type: ignore[attr-defined]

    findings: list[str] = []
    async with owner_engine.connect() as conn:
        columns = (await conn.execute(_SCANNABLE_COLUMNS)).mappings().all()
        assert columns, "no columns to scan: the schema is not migrated"

        for column in columns:
            table, name = column["table_name"], column["column_name"]
            # Cast to text so bytea, arrays and enums are all searchable with
            # one query rather than three special cases.
            hits = (
                await conn.execute(
                    text(
                        f'SELECT count(*) FROM "{table}" '
                        f'WHERE "{name}"::text LIKE :access OR "{name}"::text LIKE :refresh'
                    ),
                    {"access": f"%{access}%", "refresh": f"%{refresh}%"},
                )
            ).scalar()
            if hits:
                findings.append(f"{table}.{name} ({hits} row(s))")

    assert not findings, "plaintext tokens found in: " + ", ".join(findings)


async def test_the_credential_row_holds_ciphertext_and_a_key_version(
    api: object, owner_engine: AsyncEngine, fake_oauth: object
) -> None:
    await sign_in(api)

    async with owner_engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT access_ciphertext, refresh_ciphertext, dek_wrapped, key_version "
                        "FROM oauth_credentials"
                    )
                )
            )
            .mappings()
            .one()
        )

    assert row["key_version"] >= 1, "without a key version the key cannot be rotated"
    for field in ("access_ciphertext", "refresh_ciphertext", "dek_wrapped"):
        blob = bytes(row[field])
        # 12-byte nonce plus a 16-byte GCM tag, so anything shorter is not
        # an AES-GCM ciphertext at all.
        assert len(blob) > 28, f"{field} is too short to be sealed"
        assert fake_oauth.access_token.encode() not in blob  # type: ignore[attr-defined]
        assert fake_oauth.refresh_token.encode() not in blob  # type: ignore[attr-defined]


async def test_tokens_are_never_even_passed_to_a_log_call(api: object, fake_oauth: object) -> None:
    """Capture every log line emitted during a sign-in and read them all.

    ``capture_logs`` intercepts the event *before* the redaction processor
    runs, which makes this the stronger claim: a token is never handed to a
    log call in the first place, so no redaction list has to be complete for
    the guarantee to hold. That redaction works for the fields that are
    passed is a separate test.
    """
    with structlog.testing.capture_logs() as captured:
        await sign_in(api)

    assert captured, "the sign-in path emitted no logs at all, which is its own problem"
    blob = repr(captured)
    assert fake_oauth.access_token not in blob  # type: ignore[attr-defined]
    assert fake_oauth.refresh_token not in blob  # type: ignore[attr-defined]
    assert "code_verifier" not in blob
    assert "client_secret" not in blob
