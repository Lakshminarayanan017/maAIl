"""set_tenant refuses the two ways it could silently do nothing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.tenancy import set_tenant


async def test_requires_an_open_transaction() -> None:
    """SET LOCAL outside a transaction has no effect and no error.

    Which would mean every subsequent query returns nothing, for reasons that
    look nothing like the cause. Fail at the call instead.
    """
    session = MagicMock()
    session.in_transaction.return_value = False
    session.execute = AsyncMock()

    with pytest.raises(RuntimeError, match="open transaction"):
        await set_tenant(session, uuid4())
    session.execute.assert_not_awaited()


async def test_refuses_a_string_user_id() -> None:
    """A str would be interpolated nowhere, but typing is the cheap guard."""
    session = MagicMock()
    session.in_transaction.return_value = True
    session.execute = AsyncMock()

    with pytest.raises(TypeError):
        await set_tenant(session, "00000000-0000-4000-8000-00000000000a")  # type: ignore[arg-type]


async def test_binds_the_user_id_as_a_parameter() -> None:
    """Not interpolated. SET takes no bind parameters, set_config does.

    This is the one code path that must not be an injection site.
    """
    session = MagicMock()
    session.in_transaction.return_value = True
    session.execute = AsyncMock()
    user_id = uuid4()

    await set_tenant(session, user_id)

    statement, params = session.execute.await_args.args
    assert "set_config" in str(statement)
    assert params == {"user_id": str(user_id)}
