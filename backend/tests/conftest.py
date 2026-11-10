"""测试装配：TestClient 直连应用实例，不启动真实 uvicorn。

每个用例用独立的临时库文件，既避免污染 `backend/data/trading.db`，
也保证用例之间没有残留数据。

假 OKX 提供两种形态：
- `fake_okx_app`：进程内 ASGI 应用，用 `TestClient` 直连，不占端口。
- `fake_okx_server`：后台线程监听真实端口，供同步 `httpx.BaseTransport`
  的真实适配器连接（`httpx.ASGITransport` 只支持异步，不能替代）。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.engine import get_engine
from app.main import create_app
from tests.fakes.okx.app import create_app as create_fake_okx_app
from tests.fakes.okx.server import FakeOkxServer, start_server


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把库文件指向临时目录；用完清掉配置与引擎缓存。"""

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "trading.db"))
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """会触发 lifespan（建表）的客户端。"""

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def fake_okx_app() -> FastAPI:
    """进程内假 OKX（不占端口）。"""

    return create_fake_okx_app()


@pytest.fixture()
def fake_okx_server() -> Iterator[FakeOkxServer]:
    """真实监听 127.0.0.1 的假 OKX，退出时关闭线程。"""

    with start_server(port=0) as server:
        yield server


@pytest.fixture()
def fake_okx_settings(fake_okx_server: FakeOkxServer) -> Settings:
    """指向假 OKX 的配置：关掉重试，让故障在第一次请求就暴露。"""

    return Settings(
        okx_rest_base_url=fake_okx_server.base_url,
        okx_http_max_retries=0,
        okx_rate_limit_capacity=1000,
        okx_rate_limit_refill_per_second=1000.0,
    )
