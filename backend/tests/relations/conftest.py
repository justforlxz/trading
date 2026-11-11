"""relations 域测试装配：每个用例一个临时 schema，这里只负责执行迁移。

根 `conftest.py` 已把引擎指向本用例独有的 schema。
"""

import pytest

from app.db import init_db

# 导入即注册表元数据（与 `app.main` 的装配路径一致）。
from app.instrument import Instrument  # noqa: F401
from app.market import Candle  # noqa: F401
from app.watchlist import WatchlistItemRow  # noqa: F401


@pytest.fixture(autouse=True)
def _relations_schema() -> None:
    """每个用例开始前执行迁移建好表；schema 由根 conftest 隔离。"""

    init_db()
