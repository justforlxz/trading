"""jobs 域测试装配：需要数据库的用例在这里执行迁移。

根 `conftest.py` 已把引擎指向本用例独有的 schema；队列用例不读库，因此这个夹具不是
autouse 的，由需要的用例显式声明。
"""

import pytest

from app.db import init_db


@pytest.fixture()
def job_schema() -> None:
    """把库结构推进到最新版本；schema 由根 conftest 隔离。"""

    init_db()
