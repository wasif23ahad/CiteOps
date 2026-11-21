from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


class _FakeCursor:
    def __init__(self, pgvector_enabled: bool = True) -> None:
        self._pgvector_enabled = pgvector_enabled
        self._last_query = ""

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, query: str) -> None:
        self._last_query = query

    async def fetchone(self) -> tuple[Any, ...] | None:
        if "server_version" in self._last_query:
            return ("17.4",)
        if "pg_extension" in self._last_query:
            return ("0.8.6",) if self._pgvector_enabled else None
        return None


class _FakeConn:
    def __init__(self, pgvector_enabled: bool = True) -> None:
        self._pgvector_enabled = pgvector_enabled

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(pgvector_enabled=self._pgvector_enabled)


class _FakePool:
    def __init__(self, pgvector_enabled: bool = True) -> None:
        self._pgvector_enabled = pgvector_enabled

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield _FakeConn(pgvector_enabled=self._pgvector_enabled)


class _FakeRedis:
    def __init__(self, healthy: bool = True) -> None:
        self._healthy = healthy

    async def ping(self) -> bool:
        if not self._healthy:
            raise ConnectionError("Redis offline")
        return True


@pytest.mark.asyncio
async def test_health_ok() -> None:
    app = create_app(Settings(app_env="test", citeops_internal_api_key="secret-test-key"))
    app.state.db_pool = _FakePool(pgvector_enabled=True)
    app.state.redis = _FakeRedis(healthy=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    body = resp.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["postgres"]["status"] == "ok"
    assert body["dependencies"]["pgvector"]["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_redis_offline() -> None:
    app = create_app(Settings(app_env="test", citeops_internal_api_key=""))
    app.state.db_pool = _FakePool(pgvector_enabled=True)
    app.state.redis = _FakeRedis(healthy=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["redis"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_unhealthy_when_pgvector_missing() -> None:
    app = create_app(Settings(app_env="test", citeops_internal_api_key=""))
    app.state.db_pool = _FakePool(pgvector_enabled=False)
    app.state.redis = _FakeRedis(healthy=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_internal_api_key_enforced_on_non_public_routes() -> None:
    app = create_app(Settings(app_env="test", citeops_internal_api_key="top-secret"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.get("/v1/protected-placeholder")
        authorized = await client.get(
            "/v1/protected-placeholder",
            headers={"X-Internal-API-Key": "top-secret"},
        )

    assert unauthorized.status_code == 401
    # Authorized request passes auth middleware and hits FastAPI 404 (route not registered yet)
    assert authorized.status_code == 404
