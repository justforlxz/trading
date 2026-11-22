"""测试装配：TestClient 直连应用实例，不启动真实 uvicorn。

## 数据库隔离

整个进程共用一个已迁移的库（`trading_test_<进程号>`），会话开始时用
`alembic upgrade head` 推一次，之后用例之间靠事务回滚隔离，不再为每个用例建库删库：

- 默认：会话绑到「一条连接 + 外层事务」上（`set_session_scope_factory`），每个用例
  再套一层 savepoint，用例结束整体回滚，表回到空状态。
- 用例确实需要独立库时才标 `@pytest.mark.dedicated_database`：这类用例要跑
  `alembic downgrade`、要看跨连接已提交的数据，或要让多个线程各自连库。它们从模板库
  克隆一份 `trading_test_*`，用完连库一起删掉。

两种情况表结构都只由 `alembic upgrade head` 产生（共享库与模板库各推一次）。

模板库名带进程号（`trading_tmpl_<进程号>`），只在本进程内删除与重建：同一台机器上
同时跑两份测试（QA 全量、返工另跑一次）时各用各的模板库，互不删库。

## 测试模式

会话开始就把 `TEST_MODE=1` 写进环境：应用的 lifespan 因此不跑迁移、不启动权益快照
线程与常驻推送集线器、也不装通知管道——这些由测试装配自己准备，用例需要时再覆盖
`TEST_MODE` 后建应用。生产路径不受影响（`TEST_MODE` 默认关闭）。

数据库本身要先用 `make db-up` 起好（本地 podman 容器），所有用例共用这一台
PostgreSQL；进程被强杀留下的测试库用 `make test-clean` 清理。

假 OKX 提供两种形态：
- `fake_okx_app`：进程内 ASGI 应用，用 `TestClient` 直连，不占端口。
- `fake_okx_server`：后台线程监听真实端口，供同步 `httpx.BaseTransport`
  的真实适配器连接（`httpx.ASGITransport` 只支持异步，不能替代）。
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import init_db, set_session_scope_factory
from app.db.engine import get_engine
from app.main import create_app
from tests.db_admin import (
    TEST_DATABASE_PREFIX,
    create_database,
    database_url_with,
    drop_database,
    maintenance_engine,
    template_database_name,
)
from tests.fakes.okx.app import create_app as create_fake_okx_app
from tests.fakes.okx.server import FakeOkxServer, start_server
from tests.fakes.on_demand import RecordingScheduler

_DATABASE_URL_ENV = "DATABASE_URL"

#: 本进程配置里的库地址（不含用例库名）；会话开始时固定，之后不再从环境变量读。
_base_database_url = ""
#: 建库删库共用一条自动提交连接；第一次真要建库时才创建。
_admin_engine: Engine | None = None
#: 本进程的模板库名：会话开始时按进程号定下，同机并发跑测试时各用各的。
_template_database = ""
#: 全进程共用的那个库，以及它上面那条「外层事务」连接。
_shared_database = ""
_shared_engine: Engine | None = None
_shared_connection: Connection | None = None


def _admin() -> Engine:
    """建库删库用的引擎；必须在 `_database_session` 之后调用。"""

    assert _admin_engine is not None, "数据库会话装配还没完成"
    return _admin_engine


def _migrate(base_url: str, database: str) -> None:
    """在指定库上执行 `alembic upgrade head`：表结构的唯一产生路径。"""

    previous_url = os.environ.get(_DATABASE_URL_ENV)
    previous_schema = os.environ.pop("DATABASE_SCHEMA", None)
    os.environ[_DATABASE_URL_ENV] = database_url_with(base_url, database)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        init_db()
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        if previous_url is None:
            os.environ.pop(_DATABASE_URL_ENV, None)
        else:
            os.environ[_DATABASE_URL_ENV] = previous_url
        if previous_schema is not None:
            os.environ["DATABASE_SCHEMA"] = previous_schema


@contextmanager
def _savepoint_session() -> Iterator[Session]:
    """用例内的会话：绑在共享连接上，一次提交只释放自己的 savepoint。

    `create_savepoint` 让会话不接管外层事务：进入发 `SAVEPOINT`，提交发 `RELEASE`，
    异常发 `ROLLBACK TO SAVEPOINT`。外层事务由夹具在用例结束时统一回滚。
    """

    assert _shared_connection is not None, "共享连接还没建立"
    with (
        Session(
            bind=_shared_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session,
        session.begin(),
    ):
        yield session


@pytest.fixture(scope="session", autouse=True)
def _database_session() -> Iterator[None]:
    """建好本进程共用的库并迁移到最新版本，再建模板库供独立库用例克隆。"""

    global _base_database_url, _admin_engine, _template_database
    global _shared_database, _shared_engine, _shared_connection

    get_settings.cache_clear()
    _base_database_url = get_settings().database_url
    engine = maintenance_engine(_base_database_url)
    try:
        engine.connect().close()
    except Exception as exc:
        engine.dispose()
        target = make_url(_base_database_url)
        # 不串接原始异常：pytest 会把第三方库帧的局部变量打进 traceback，而 psycopg 的帧里
        # 就带着明文口令。失败原因已按「类型 + 消息」写进本条报错，不再需要原始 traceback。
        raise RuntimeError(
            f"连接测试数据库失败({target.host}:{target.port}/{target.database}): "
            f"{type(exc).__name__}: {exc}; 先执行 `make db-up` 起本地 PostgreSQL"
        ) from None
    _admin_engine = engine

    _template_database = template_database_name()
    _shared_database = f"{TEST_DATABASE_PREFIX}{os.getpid()}"
    try:
        # 只处理本进程自己的库：同机并发的另一个 pytest 进程有它自己的库名，
        # 无条件按固定名字删会把别人正在迁移的库强杀掉。
        drop_database(engine, _template_database)
        create_database(engine, _template_database)
        _migrate(_base_database_url, _template_database)

        # 共享库直接克隆迁移好的模板库：整场会话只跑一次迁移。
        drop_database(engine, _shared_database)
        create_database(engine, _shared_database, template=_template_database)

        # 整场会话都指向共享库；用例不再改这一项。
        os.environ[_DATABASE_URL_ENV] = database_url_with(_base_database_url, _shared_database)
        os.environ.pop("DATABASE_SCHEMA", None)
        os.environ["TEST_MODE"] = "1"
        get_settings.cache_clear()
        get_engine.cache_clear()

        _shared_engine = get_engine()
        _shared_connection = _shared_engine.connect()
        # 外层事务贯穿整场会话，任何用例的提交都只落在这里，结束时一次回滚。
        _shared_connection.begin()
        try:
            yield
        finally:
            _shared_connection.rollback()
            _shared_connection.close()
            _shared_connection = None
            _shared_engine.dispose()
            _shared_engine = None
            get_engine.cache_clear()
            drop_database(engine, _shared_database)
            drop_database(engine, _template_database)
    finally:
        _admin_engine = None
        engine.dispose()


@contextmanager
def _dedicated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """给单个用例从模板库克隆一个独立库；用完连库一起删掉（失败也照删）。

    独立库用例不经过共享连接，因此可以跑迁移、跨连接读已提交数据、多线程各自连库。
    """

    database = f"{TEST_DATABASE_PREFIX}{uuid4().hex}"
    create_database(_admin(), database, template=_template_database)
    monkeypatch.setenv(_DATABASE_URL_ENV, database_url_with(_base_database_url, database))
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()
    try:
        yield
    finally:
        # 先关掉本用例的连接池再删库：池里残留的连接会让库删不掉。
        engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        drop_database(_admin(), database)


@pytest.fixture(autouse=True)
def _isolated_database(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """把本用例的数据改动关在 savepoint 里（`dedicated_database` 用例改用独立库）。"""

    if request.node.get_closest_marker("dedicated_database"):
        with _dedicated_database(monkeypatch):
            yield
        return

    assert _shared_connection is not None, "共享连接还没建立"
    set_session_scope_factory(_savepoint_session)
    savepoint = _shared_connection.begin_nested()
    try:
        yield
    finally:
        set_session_scope_factory(None)
        savepoint.rollback()


@pytest.fixture(autouse=True)
def _reset_macro_runtime() -> Iterator[None]:
    """宏观同步状态是进程内的：用例之间清空，避免失败/退避互相污染。"""

    from app.macro import service

    service.reset_runtime()
    yield
    service.reset_runtime()


@pytest.fixture()
def sync_scheduler() -> RecordingScheduler:
    """默认注入的记录型调度器；自选用例据此断言同步被请求了一次。"""

    return RecordingScheduler()


@pytest.fixture()
def client(sync_scheduler: RecordingScheduler) -> Iterator[TestClient]:
    """会触发 lifespan 的客户端；库结构已由会话夹具推好，lifespan 在测试模式下跳过它。

    默认不启动真实按需同步线程：加入自选的用例很多，不能因为一次测试就访问上游。
    需要真实队列的用例自行替换 `client.app.state.on_demand_sync`。
    """

    with TestClient(create_app(on_demand_sync=sync_scheduler)) as test_client:
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
