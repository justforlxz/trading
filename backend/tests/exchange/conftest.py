"""私有交易接口用例的公共装配：假 OKX（含交易域）、凭据、固定时钟、标的表。

假 OKX 是**真实监听端口**的进程内服务：私有客户端用的是同步 `httpx.Client`，
`httpx.ASGITransport` 只支持异步，不能替代。

时钟固定成 `2026-11-10T04:26:00Z`：签名时间戳因此在用例里可复现，断言不必容忍抖动。
标的表按「上游快照 → 交换层解析 → 落库」的同一条路径写入，不在测试里手拼 ORM 行。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.core import Clock, ReplayClock
from app.db import init_db
from app.exchange import OkxPrivateClient, create_trade_port
from app.exchange.okx.instruments import parse_instruments
from app.instrument import sync_instruments
from tests.fakes.okx.server import FakeOkxServer

SPOT = "SPOT"
SWAP = "SWAP"
SPOT_INST_ID = "XAAPL-USDT"
SWAP_INST_ID = "AAPL-USDT-SWAP"
FROZEN_NOW = datetime(2026, 11, 10, 4, 26, 0, tzinfo=UTC)

# 与 `tests/exchange/test_market.py` 同形：就是上游 `/public/instruments` 的行格式。
SPOT_INSTRUMENT = {
    "instId": SPOT_INST_ID,
    "instType": SPOT,
    # 代币化股票的现货侧币种带 `X` 前缀：产品键由标的模块从这一列推出。
    "baseCcy": "XAAPL",
    "quoteCcy": "USDT",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.001",
    "minSz": "0.01",
    "listTime": "1760000000000",
}

SWAP_INSTRUMENT = {
    "instId": SWAP_INST_ID,
    "instType": SWAP,
    "baseCcy": "",
    "quoteCcy": "",
    "ctValCcy": "AAPL",
    "settleCcy": "USDT",
    "ctVal": "1",
    "ctMult": "1",
    "ctType": "linear",
    "lever": "20",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.1",
    "minSz": "0.1",
    "listTime": "1760000000000",
}


@pytest.fixture()
def trade_schema() -> None:
    """建表（迁移）：幂等登记表与标的表都要真的存在，schema 由根 conftest 隔离。"""

    init_db()


@pytest.fixture()
def instruments(trade_schema: None) -> None:
    """把两条标的写进标的表：适配层解析类别与币种映射都只认这张表。"""

    sync_instruments(parse_instruments([SPOT_INSTRUMENT, SWAP_INSTRUMENT]))


@pytest.fixture()
def frozen_clock() -> Clock:
    return ReplayClock(FROZEN_NOW)


@pytest.fixture()
def private_settings(fake_okx_server: FakeOkxServer) -> Settings:
    """指向假 OKX 的配置：关掉重试，让故障在第一次请求就暴露。"""

    credentials = fake_okx_server.store.book.credentials
    return Settings(
        okx_rest_base_url=fake_okx_server.base_url,
        okx_http_max_retries=0,
        okx_rate_limit_capacity=1000,
        okx_rate_limit_refill_per_second=1000.0,
        okx_api_key=credentials.api_key,
        okx_secret_key=credentials.secret,
        okx_passphrase=credentials.passphrase,
        okx_demo=True,
    )


@pytest.fixture()
def trade(
    private_settings: Settings,
    frozen_clock: Clock,
    instruments: None,
) -> Iterator[OkxPrivateClient]:
    """签名正确的私有客户端；标的表已就绪，用例可以直接下单。"""

    client = create_trade_port(settings=private_settings, clock=frozen_clock)
    yield client
    client.close()
