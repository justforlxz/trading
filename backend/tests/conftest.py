"""测试装配：TestClient 直连应用实例，不启动真实 uvicorn。

每个用例一个独立临时 schema：用例开始时建 schema 并把引擎的 `search_path` 指向它，
结束时整块删掉。表结构与 Alembic 版本表都落在该 schema 内，因此用例之间没有残留
数据，也不需要为每个用例建一个库。

数据库本身要先用 `make db-up` 起好（本地 podman 容器），所有用例共用一个库。

假 OKX 提供两种形态：
- `fake_okx_app`：进程内 ASGI 应用，用 `TestClient` 直连，不占端口。
- `fake_okx_server`：后台线程监听真实端口，供同步 `httpx.BaseTransport`
  的真实适配器连接（`httpx.ASGITransport` 只支持异步，不能替代）。
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import Settings, get_settings
from app.db.engine import get_engine
from app.main import create_app
from tests.fakes.okx.app import create_app as create_fake_okx_app
from tests.fakes.okx.server import FakeOkxServer, start_server


def _run_on_server(database_url: str, statement: str) -> None:
    """在库级连接（不指定 schema）上执行一条语句，执行完立即释放连接池。"""

    engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把库结构隔离到本用例独有的 schema；用完连同数据一起删掉。"""

    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    database_url = get_settings().database_url

    schema = f"test_{uuid4().hex}"
    try:
        _run_on_server(database_url, f'CREATE SCHEMA "{schema}"')
    except Exception as exc:  # 连接层失败最常见的原因是库没起，直接给出下一步动作。
        raise RuntimeError(
            f"连接测试数据库失败({database_url}), 先执行 `make db-up` 起本地 PostgreSQL"
        ) from exc

    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_engine.cache_clear()
    get_settings.cache_clear()
    _run_on_server(database_url, f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """会触发 lifespan（执行迁移）的客户端。"""

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
