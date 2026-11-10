"""同步 PostgreSQL 引擎：连接串来自配置，schema 可选。

引擎按配置惰性创建并缓存：测试可以通过 `get_engine.cache_clear()` 换连接，
不需要重载模块。

`schema` 不为空时，每条连接都把 `search_path` 钉到该 schema：表与 Alembic 的
版本表都落在里面，测试因此可以各自用一个临时 schema 互不干扰，不用建临时库。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings


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
def session_scope() -> Iterator[Session]:
    """一次工作单元的会话：正常提交，异常回滚，最后关闭。

    提交后不让实例过期：域服务会把查到的行作为只读对象交给上层，出作用域后
    再读属性不应该触发 `DetachedInstanceError`。
    """

    with Session(get_engine(), expire_on_commit=False) as session, session.begin():
        yield session
