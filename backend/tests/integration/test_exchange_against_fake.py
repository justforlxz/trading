"""真实 `OkxClient` 指向假 OKX：验证归一化 DTO 与错误收敛。

适配器的传输层是同步 `httpx.BaseTransport`，所以这里连真实端口，
而不是 `httpx.ASGITransport`（只支持异步）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.exchange import (
    ExchangeError,
    InstrumentInfo,
    OkxClient,
    OkxMarketData,
    RateLimitedError,
)
from tests.fakes.okx.server import FakeOkxServer

SPOT_ID = "XAAPL-USDT"
_INSTRUMENTS_PATH = "/api/v5/public/instruments"


@pytest.fixture()
def market(fake_okx_settings: Settings) -> Iterator[OkxMarketData]:
    data = OkxMarketData(OkxClient(settings=fake_okx_settings))
    try:
        yield data
    finally:
        data.close()


def test_instruments_are_normalised_to_the_port_dto(market: OkxMarketData) -> None:
    instruments = market.instruments()

    assert len(instruments) == 199
    assert all(isinstance(item, InstrumentInfo) for item in instruments)
    assert {item.inst_type for item in instruments} == {"SPOT"}

    sample = next(item for item in instruments if item.inst_id == SPOT_ID)
    assert sample.base_ccy == "XAAPL"
    assert sample.quote_ccy == "USDT"
    assert sample.state == "live"
    assert sample.inst_category == "3"
    assert sample.tick_size == Decimal("0.01")
    assert sample.lot_size == Decimal("0.00001")
    assert sample.min_size == Decimal("0.01")
    assert sample.list_time == datetime.fromtimestamp(1784181600, tz=UTC)


def test_candles_come_back_in_ascending_time_order(market: OkxMarketData) -> None:
    candles = market.candles(SPOT_ID, "1d", limit=5)

    assert len(candles) == 5
    open_times = [candle.open_time for candle in candles]
    assert open_times == sorted(open_times)
    assert {candle.bar for candle in candles} == {"1d"}
    assert {candle.source for candle in candles} == {"okx"}
    assert candles[-1].confirm is False
    assert all(candle.confirm for candle in candles[:-1])
    assert all(isinstance(candle.open, Decimal) for candle in candles)


def test_daily_candles_open_at_sixteen_utc(market: OkxMarketData) -> None:
    for candle in market.candles(SPOT_ID, "1d", limit=5):
        assert candle.open_time.tzinfo is not None
        assert int(candle.open_time.timestamp()) % 86400 == 57600


def test_history_candles_page_strictly_before_the_cursor(market: OkxMarketData) -> None:
    recent = market.candles(SPOT_ID, "1h", limit=5)
    cursor = recent[0].open_time

    older = market.history_candles(SPOT_ID, "1h", after=cursor, limit=5)

    assert older
    assert all(candle.open_time < cursor for candle in older)
    assert all(candle.confirm for candle in older)


def test_ticker_is_normalised(market: OkxMarketData) -> None:
    ticker = market.ticker(SPOT_ID)

    assert ticker.inst_id == SPOT_ID
    assert ticker.bid < ticker.last < ticker.ask
    assert isinstance(ticker.volume_24h, Decimal)
    assert ticker.ts.tzinfo is not None


def test_rate_limit_is_surfaced_as_rate_limited_error(
    fake_okx_server: FakeOkxServer, fake_okx_settings: Settings
) -> None:
    fake_okx_server.scenarios.activate("rate_limited")

    with OkxClient(settings=fake_okx_settings) as client, pytest.raises(RateLimitedError):
        client.get(_INSTRUMENTS_PATH, {"instType": "SPOT"})


def test_upstream_failure_is_surfaced_as_exchange_error(
    fake_okx_server: FakeOkxServer, fake_okx_settings: Settings
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    with OkxClient(settings=fake_okx_settings) as client, pytest.raises(ExchangeError) as caught:
        client.get(_INSTRUMENTS_PATH, {"instType": "SPOT"})

    assert not isinstance(caught.value, RateLimitedError)
