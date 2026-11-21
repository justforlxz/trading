"""market 域测试装配：每个用例一个独立临时库，行情走线程内假 OKX。

库与表结构都由根 `conftest.py` 准备好（模板库克隆，迁移已在模板上跑过）；这里只负责
把真实适配器（`OkxMarketData`）指向假 OKX。
"""

from collections.abc import Iterator

import pytest

from app.exchange import OkxMarketData, create_market_data

# 导入即注册 `candles` 表元数据（与 `app.main` 的装配路径一致）。
from app.market import Candle  # noqa: F401


@pytest.fixture()
def market_port(fake_okx_settings) -> Iterator[OkxMarketData]:
    """指向假 OKX 的真实行情适配器。"""

    port = create_market_data(settings=fake_okx_settings)
    yield port
    port.close()
