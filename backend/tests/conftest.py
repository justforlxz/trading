"""pytest 公共夹具。

S2 的集成测试走 ASGI 传输层，不启动 uvicorn、不连数据库；需要数据库的
用例从 S3 起用 `pytest-postgresql` 或 Compose 内的实例，不在此处预埋。
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
