"""No user-scoped table without an RLS policy — against the live database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.database.audit import audit_schema

pytestmark = [pytest.mark.arch, pytest.mark.integration]


async def test_every_user_scoped_table_is_protected(owner_engine: AsyncEngine) -> None:
    settings = get_settings()
    async with owner_engine.connect() as conn:
        result = await audit_schema(conn, app_role=settings.postgres_app_user)
    assert result.ok, "\n" + result.render()
