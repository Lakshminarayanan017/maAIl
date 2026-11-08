"""Health, and the readiness check that would catch a misdeployed role."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.integration


async def test_live_needs_no_database() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_live_echoes_a_request_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/health/live", headers={"X-Request-ID": "fixed-for-the-test"}
        )
    assert response.headers["X-Request-ID"] == "fixed-for-the-test"


async def test_security_headers_are_set() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_ready_reports_a_sound_tenancy_boundary(app_engine: object) -> None:
    """Depends on app_engine purely so it skips when Postgres is down."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["problems"] == [], body["problems"]
    assert body["status"] == "ok"
    assert body["tenancy"]["rls_forced"] is True
