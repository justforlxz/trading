"""pytest 公共夹具。

数据库 URL 在**导入 app 之前**确定：`TEST_DATABASE_URL` 优先，否则把
`DATABASE_URL` 的库名换成 `trading_test`，避免误伤开发库。
"""

import os
from urllib.parse import urlsplit, urlunsplit

import pytest
from httpx import ASGITransport, AsyncClient


def _test_database_url() -> str | None:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base:
        return None
    parts = urlsplit(base)
    return urlunsplit(parts._replace(path="/trading_test"))


TEST_DATABASE_URL = _test_database_url()
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.main import create_app  # noqa: E402 - 必须在设置 DATABASE_URL 之后导入


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
