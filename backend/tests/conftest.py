"""测试装配：TestClient 直连应用实例，不启动真实 uvicorn。

数据库隔离单位是「每个用例一个独立库」：session 开始时先用 `alembic upgrade head`
把一个模板库迁移到最新版本，之后用例第一次连库时（不是每个用例开始时）从模板库
克隆一份 `trading_test_*`，用完连库一起删掉。表结构仍然只由迁移产生，用例之间也
没有任何残留数据，但既不用为每个用例把 34 张表从头迁移，纯逻辑用例也不必付建库的
代价。

模板库名带进程号（`trading_tmpl_<进程号>`），只在本进程内删除与重建：同一台机器上
同时跑两份测试（QA 全量、返工另跑一次）时各用各的模板库，互不删库。

库是「第一次真的要连数据库时」才建的，因此不依赖用例请求了哪个夹具：任何一条连接
（应用引擎、`session_scope`、迁移）都会先经过 psycopg 的连接入口，等在那里补建。

数据库本身要先用 `make db-up` 起好（本地 podman 容器），所有用例共用这一台
PostgreSQL；进程被强杀留下的测试库用 `make test-clean` 清理。

假 OKX 提供两种形态：
- `fake_okx_app`：进程内 ASGI 应用，用 `TestClient` 直连，不占端口。
- `fake_okx_server`：后台线程监听真实端口，供同步 `httpx.BaseTransport`
  的真实适配器连接（`httpx.ASGITransport` 只支持异步，不能替代）。
"""

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from app.config import Settings, get_settings
from app.db import init_db
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

_real_psycopg_connect = psycopg.connect

#: 本进程配置里的库地址（不含用例库名）；会话开始时固定，之后不再从环境变量读。
_base_database_url = ""
#: 建库删库共用一条自动提交连接；第一次真要建库时才创建。
_admin_engine: Engine | None = None
#: 本进程的模板库名：会话开始时按进程号定下，同机并发跑测试时各用各的。
_template_database = ""
#: 用例库名，以及「这一份是否已经建出来」——决定连接前要不要补建、结束时要不要删。
_current_database = ""
_current_database_created = False


def _admin() -> Engine:
    """建库删库用的引擎；必须在 `_database_session` 之后调用。"""

    assert _admin_engine is not None, "数据库会话装配还没完成"
    return _admin_engine


def _create_current_database() -> None:
    """把本用例的库从模板库克隆出来；同一个用例只建一次。"""

    global _current_database_created

    if not _current_database or _current_database_created:
        return
    # 先置位再建：建库本身要连维护库，别让连接入口重入。
    _current_database_created = True
    create_database(_admin(), _current_database, template=_template_database)


def _requested_database(args: tuple[object, ...], kwargs: dict[str, object]) -> str | None:
    """从 psycopg 的连接参数里取出目标库名（SQLAlchemy 传关键字，也兼容 conninfo 串）。"""

    dbname = kwargs.get("dbname")
    if dbname:
        return str(dbname)
    if args and isinstance(args[0], str):
        return psycopg.conninfo.conninfo_to_dict(args[0]).get("dbname")
    return None


def _connect_creating_current_database(*args: object, **kwargs: object) -> object:
    """连接入口：目标是本用例的库、且还没建，就先从模板库克隆出来。"""

    if _requested_database(args, kwargs) == _current_database:
        _create_current_database()
    return _real_psycopg_connect(*args, **kwargs)


def _migrate(base_url: str, database: str) -> None:
    """在指定库上执行 `alembic upgrade head`：表结构的唯一产生路径。"""

    previous_url = os.environ.get("DATABASE_URL")
    previous_schema = os.environ.pop("DATABASE_SCHEMA", None)
    os.environ["DATABASE_URL"] = database_url_with(base_url, database)
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        init_db()
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        if previous_schema is not None:
            os.environ["DATABASE_SCHEMA"] = previous_schema


@pytest.fixture(scope="session", autouse=True)
def _database_session() -> Iterator[None]:
    """把模板库迁移到最新版本，并把库的建删接到 psycopg 的连接入口上。"""

    global _base_database_url, _admin_engine, _template_database

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
    try:
        # 只处理本进程自己的模板库：同机并发的另一个 pytest 进程有它自己的模板库，
        # 无条件按固定名字删会把别人正在迁移的库强杀掉。
        drop_database(engine, _template_database)
        create_database(engine, _template_database)
        _migrate(_base_database_url, _template_database)
        patch = pytest.MonkeyPatch()
        patch.setattr(psycopg, "connect", _connect_creating_current_database)
        try:
            yield
        finally:
            patch.undo()
            drop_database(engine, _template_database)
    finally:
        _admin_engine = None
        engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_database(monkeypatch: pytest.MonkeyPatch, _database_session: None) -> Iterator[None]:
    """把本用例指向自己的库；真的连库时才建，用完连库一起删掉（失败也照删）。"""

    global _current_database, _current_database_created

    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    database = f"{TEST_DATABASE_PREFIX}{uuid4().hex}"
    _current_database, _current_database_created = database, False
    monkeypatch.setenv("DATABASE_URL", database_url_with(_base_database_url, database))
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        yield
    finally:
        # 先关掉本用例的连接池再删库：池里残留的连接会让库删不掉。
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()
        created = _current_database_created
        _current_database, _current_database_created = "", False
        if created:
            drop_database(_admin(), database)


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
    """会触发 lifespan 的客户端；库从模板库克隆而来，lifespan 里的迁移是空操作。

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
