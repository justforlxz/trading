"""健康探针与 API 前缀的集成测试（覆盖 S2 验收条件 1、3）。"""

from httpx import AsyncClient

from app import __version__


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_health_is_not_versioned(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 404


async def test_api_v1_prefix_is_mounted(client: AsyncClient) -> None:
    response = await client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {"name": "trading", "version": __version__}
