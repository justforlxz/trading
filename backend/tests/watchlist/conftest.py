"""watchlist 域测试装配：每个用例一个临时库，这里只负责建表。

根 `conftest.py` 已把 `DATABASE_PATH` 指到 `tmp_path`。
"""

import pytest

from app.db import init_db

# 导入即注册表元数据（与 `app.main` 的装配路径一致）。
from app.instrument import Instrument  # noqa: F401
from app.market import Candle  # noqa: F401
from app.watchlist import WatchlistItemRow  # noqa: F401


@pytest.fixture(autouse=True)
def _watchlist_schema() -> None:
    """每个用例开始前建好表；库文件由根 conftest 隔离。"""

    init_db()
