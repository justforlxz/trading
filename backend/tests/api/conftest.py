"""API 用例共用的真实落库数据：标的与日线都走业务写入路径，不手写响应形状。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import Bar, InstrumentRef, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from tests.factories.instruments import make_ref, make_swap_ref

DAY = timedelta(days=1)
LOOKBACK_DAYS = 3


def seed_instruments(*refs: InstrumentRef) -> None:
    """按交换层的返回值写库，形状与生产同步路径完全一致。"""

    sync_instruments(list(refs))


def latest_opens(count: int) -> list[datetime]:
    """最近若干日线的开盘时间：足够接近当下，落在默认 30 天窗口内。"""

    base = (datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    return [base + DAY * index for index in range(count)]


def seed_daily(inst_id: str, closes: list[str], *, volume: str = "10") -> None:
    """把收盘序列写成一串已完结日线；成交量固定，便于断言近似成交额。"""

    rows = [
        Bar(
            inst_id=inst_id,
            timeframe=Timeframe.parse("1d"),
            open_time=open_time,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal(volume),
            confirm=True,
            source="okx",
        )
        for open_time, close in zip(latest_opens(len(closes)), closes, strict=True)
    ]
    upsert_candles(rows)


@pytest.fixture
def market_data(client: TestClient) -> TestClient:
    """一现货一永续两条腿、各三根日线；用例在此基础上按需自增。"""

    seed_instruments(make_ref(), make_swap_ref())
    seed_daily("XAAPL-USDT", ["100", "110", "121"])
    seed_daily("AAPL-USDT-SWAP", ["50", "55", "60.5"])
    return client


@pytest.fixture
def quote_less_instrument(client: TestClient) -> TestClient:
    """已同步但没有任何日线的标的：行情字段无从计算。"""

    seed_instruments(make_ref(inst_id="XETH-USDT", base_ccy="XETH"))
    return client
