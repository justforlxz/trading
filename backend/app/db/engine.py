"""同步 SQLite 引擎：单文件库 + WAL + 外键约束。

`journal_mode` 是库文件级属性，写入一次后随文件持久化；仍在每次建连时显式设置，
因为库文件可能由外部工具创建（此时默认是 `delete` 模式）。

引擎按配置惰性创建并缓存：测试可以通过 `get_engine.cache_clear()` 换库，
不需要重载模块。
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from app.config import get_settings

# 写锁等待 5s：单进程下不预期争用，留出足够余量避免长事务直接报 locked。
BUSY_TIMEOUT_MS = 5000


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """每次新建连接都执行的库级设置。"""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


@lru_cache
def get_engine() -> Engine:
    """按配置构造引擎；父目录不存在时先建目录。"""

    database_path = get_settings().database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{database_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _set_sqlite_pragmas)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """一次工作单元的会话：正常提交，异常回滚，最后关闭。"""

    with Session(get_engine()) as session, session.begin():
        yield session
