"""market 域测试装配：每个用例一个临时库，行情走线程内假 OKX。

根 `conftest.py` 已把 DATABASE_PATH 指到 `tmp_path`；这里只负责建表、
以及把真实适配器（`OkxMarketData`）指向假 OKX。
"""

from collections.abc import Iterator

import pytest

from app.db import init_db
from app.exchange import OkxMarketData, create_market_data

# 导入即注册 `candles` 表元数据（与 `app.main` 的装配路径一致）。
from app.market import Candle  # noqa: F401


@pytest.fixture(autouse=True)
def _candles_schema() -> None:
    """每个用例开始前建好表；库文件由根 conftest 隔离。"""

    init_db()


@pytest.fixture()
def market_port(fake_okx_settings) -> Iterator[OkxMarketData]:
    """指向假 OKX 的真实行情适配器。"""

    port = create_market_data(settings=fake_okx_settings)
    yield port
    port.close()
