"""测试脚手架用到的临时数据库操作。

标了 `@pytest.mark.dedicated_database` 的用例各用一个从模板库克隆出来的独立库：
表结构由模板库上的一次 `alembic upgrade head` 产生，用完连库一起删掉。其余用例走
根 `conftest.py` 的 savepoint 隔离，不经过这里。

建库、删库、查库都必须连维护库（`postgres`）：`CREATE DATABASE` / `DROP DATABASE`
不能在事务块里执行，也不能删掉自己所在的库，所以这些语句走自动提交的独立引擎。
"""

from __future__ import annotations

import os
import re

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

#: 建库删库连的维护库；测试库不能删自己。
MAINTENANCE_DATABASE = "postgres"

#: 模板库名前缀：一次迁移到最新版本，之后需要独立库的用例从它克隆。
TEMPLATE_DATABASE_PREFIX = "trading_tmpl_"

#: 用例库名前缀：一眼能看出是测试产物，也方便 `make test-clean` 清理。
TEST_DATABASE_PREFIX = "trading_test_"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _quote(identifier: str) -> str:
    """库名直接拼进 SQL，先确认它只由小写字母、数字、下划线组成。"""

    if not _IDENTIFIER.match(identifier):
        raise ValueError(f"非法的数据库名: {identifier!r}")
    return f'"{identifier}"'


def template_database_name() -> str:
    """本进程独占的模板库名：同机并发跑多个 pytest 进程时互不删库。"""

    return f"{TEMPLATE_DATABASE_PREFIX}{os.getpid()}"


def database_url_with(base_url: str, database: str) -> str:
    """把连接串的库名换成 `database`；其余参数原样保留（远端测试库可能要 sslmode）。"""

    # `str(URL)` 会把密码渲染成 `***`，连接串必须原样取回才能真正连上。
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def maintenance_engine(base_url: str) -> Engine:
    """连维护库的自动提交引擎：建库删库都必须在事务之外执行。"""

    return create_engine(
        database_url_with(base_url, MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )


def create_database(engine: Engine, database: str, template: str | None = None) -> None:
    """建库；给 `template` 时整库克隆（表、索引、约束、迁移版本一并复制）。"""

    statement = f"CREATE DATABASE {_quote(database)}"
    if template is not None:
        statement += f" TEMPLATE {_quote(template)}"
    with engine.connect() as connection:
        connection.execute(text(statement))


def drop_database(engine: Engine, database: str) -> None:
    """删库；`WITH (FORCE)` 先断开残留连接，避免库被占着删不掉。"""

    with engine.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {_quote(database)} WITH (FORCE)"))


def databases_starting_with(engine: Engine, *prefixes: str) -> list[str]:
    """按前缀列出库名；只在测试库里做字符串比较，不用 SQL 的 `LIKE`。"""

    with engine.connect() as connection:
        names = connection.execute(
            text("SELECT datname FROM pg_database ORDER BY datname")
        ).scalars()
    return [name for name in names if name.startswith(prefixes)]


def drop_databases_starting_with(engine: Engine, *prefixes: str) -> list[str]:
    """删掉所有以给定前缀开头的库，返回删掉的库名。"""

    dropped = []
    for name in databases_starting_with(engine, *prefixes):
        drop_database(engine, name)
        dropped.append(name)
    return dropped
