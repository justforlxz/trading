"""同步 PostgreSQL 引擎：连接串来自配置，schema 可选。

引擎按配置惰性创建并缓存：测试可以通过 `get_engine.cache_clear()` 换连接，
不需要重载模块。

`schema` 不为空时，每条连接都把 `search_path` 钉到该 schema：表与 Alembic 的
版本表都落在里面，测试因此可以各自用一个临时 schema 互不干扰，不用建临时库。

## 会话注入口

业务代码不自己造会话，统一经 `session_scope()` 取工作单元。`session_scope` 每次被
调用时才读当前的工作单元工厂（`_session_scope_factory`），所以进程内换一种会话来源
不需要在 60 多个调用点逐一打桩：

- 生产与常规测试用默认工厂：一次会话一条池连接，退出即提交或回滚。
- 测试装配把工厂换成「一条连接 + 外层事务 + 每个用例一个 savepoint」：会话不再各
  自拿连接，用例结束时整体回滚，表回到空状态。
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings

#: 工作单元工厂：每调用一次给出一个会话上下文，进入开事务、退出提交或回滚。
SessionScopeFactory = Callable[[], AbstractContextManager[Session]]


def _connect_args(schema: str | None) -> dict[str, Any]:
    """把 schema 变成 libpq 的 `options`；留空时用连接默认的 search_path。"""

    return {"options": f"-csearch_path={schema}"} if schema else {}


@lru_cache
def get_engine() -> Engine:
    """按配置构造引擎。"""

    settings = get_settings()
    return create_engine(
        settings.database_url,
        future=True,
        connect_args=_connect_args(settings.database_schema),
    )


@contextmanager
def _engine_session_scope() -> Iterator[Session]:
    """默认工作单元：一次会话一条池连接。"""

    with Session(get_engine(), expire_on_commit=False) as session, session.begin():
        yield session


#: 当前的工作单元工厂；测试装配替换它，生产路径始终是默认值。
_session_scope_factory: SessionScopeFactory = _engine_session_scope


def session_scope() -> AbstractContextManager[Session]:
    """一次工作单元的会话：正常提交，异常回滚，最后关闭。

    提交后不让实例过期：域服务会把查到的行作为只读对象交给上层，出作用域后
    再读属性不应该触发 `DetachedInstanceError`。
    """

    return _session_scope_factory()


def set_session_scope_factory(factory: SessionScopeFactory | None) -> None:
    """替换工作单元工厂；传 `None` 恢复默认（一次会话一条池连接）。"""

    global _session_scope_factory
    _session_scope_factory = factory or _engine_session_scope
