"""真实 `OkxClient` 指向假 OKX：验证归一化 DTO、口径与错误收敛。

适配器的传输层是同步 `httpx.BaseTransport`，所以这里连真实端口，
而不是 `httpx.ASGITransport`（只支持异步）。

两类标的各覆盖一条正常路径与一条上游错误路径；成交量一律对照上游原始行断言，
口径取错列时这里立刻变红。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.core import Bar, InstrumentRef, Timeframe, ValidationError
from app.exchange import (
    ExchangeError,
    OkxClient,
    OkxMarketData,
    RateLimitedError,
)
from tests.fakes.okx.server import FakeOkxServer

SPOT = "SPOT"
SWAP = "SWAP"
SPOT_ID = "XAAPL-USDT"
SWAP_ID = "AAPL-USDT-SWAP"
SWAP_SAMPLE = "ANTHROPIC-USDT-SWAP"

_INSTRUMENTS_PATH = "/api/v5/public/instruments"
_CANDLES_PATH = "/api/v5/market/candles"


@pytest.fixture()
def market(fake_okx_settings: Settings) -> Iterator[OkxMarketData]:
    data = OkxMarketData(OkxClient(settings=fake_okx_settings))
    try:
        yield data
    finally:
        data.close()


@pytest.fixture()
def client(fake_okx_settings: Settings) -> Iterator[OkxClient]:
    """独立的公开客户端：只用公开接口取上游原始行做对照。"""

    with OkxClient(settings=fake_okx_settings) as okx:
        yield okx


@pytest.fixture()
def timeframe() -> Timeframe:
    return Timeframe.parse("1d")


def _raw_candles(client: OkxClient, inst_id: str, limit: int = 5) -> list[tuple[str, str, str]]:
    """经公开 HTTP 接口取同一批 K 线的上游原始行，用来对照成交量口径。"""

    rows = client.get(_CANDLES_PATH, {"instId": inst_id, "bar": "1D", "limit": str(limit)})
    return [(row[0], row[5], row[6]) for row in rows]


def test_instruments_are_normalised_to_the_port_dto(market: OkxMarketData) -> None:
    instruments = market.instruments(SPOT)

    assert len(instruments) == 199
    assert all(isinstance(item, InstrumentRef) for item in instruments)
    assert {item.inst_type for item in instruments} == {SPOT}

    sample = next(item for item in instruments if item.inst_id == SPOT_ID)
    assert sample.base_ccy == "XAAPL"
    assert sample.quote_ccy == "USDT"
    assert sample.state == "live"
    assert sample.inst_category == "3"
    assert sample.tick_size == Decimal("0.01")
    assert sample.lot_size == Decimal("0.00001")
    assert sample.min_size == Decimal("0.01")
    assert sample.list_time == datetime.fromtimestamp(1784181600, tz=UTC)


def test_swap_instruments_fall_back_to_contract_currencies(market: OkxMarketData) -> None:
    """永续行的 `baseCcy` / `quoteCcy` 是空串，币种改由 `ctValCcy` / `settleCcy` 给出。"""

    instruments = market.instruments(SWAP)

    assert len(instruments) == 230
    assert {item.inst_type for item in instruments} == {SWAP}

    sample = next(item for item in instruments if item.inst_id == SWAP_SAMPLE)
    assert sample.base_ccy == "ANTHROPIC"
    assert sample.quote_ccy == "USDT"
    assert sample.ct_val_ccy == "ANTHROPIC"
    assert sample.settle_ccy == "USDT"


def test_candles_come_back_in_ascending_time_order(
    market: OkxMarketData, timeframe: Timeframe
) -> None:
    candles = market.candles(SPOT_ID, timeframe, inst_type=SPOT, limit=5)

    assert len(candles) == 5
    assert all(isinstance(candle, Bar) for candle in candles)
    open_times = [candle.open_time for candle in candles]
    assert open_times == sorted(open_times)
    assert {candle.timeframe for candle in candles} == {timeframe}
    assert {candle.source for candle in candles} == {"okx_spot"}
    assert candles[-1].confirm is False
    assert all(candle.confirm for candle in candles[:-1])
    assert all(isinstance(candle.open, Decimal) for candle in candles)


def test_spot_candles_take_volume_from_the_vol_column(
    market: OkxMarketData, client: OkxClient, timeframe: Timeframe
) -> None:
    candles = market.candles(SPOT_ID, timeframe, inst_type=SPOT, limit=5)
    raw = {open_ms: (vol, vol_ccy) for open_ms, vol, vol_ccy in _raw_candles(client, SPOT_ID)}

    for candle in candles:
        open_ms = str(round(candle.open_time.timestamp() * 1000))
        vol, vol_ccy = raw[open_ms]
        assert candle.volume == Decimal(vol)
        # 现货的 `volCcy` 是计价额，与标的币数量不是一个量级；取错列必然不等。
        assert candle.volume != Decimal(vol_ccy)


def test_swap_candles_take_volume_from_the_vol_ccy_column(
    market: OkxMarketData, client: OkxClient, timeframe: Timeframe
) -> None:
    candles = market.candles(SWAP_ID, timeframe, inst_type=SWAP, limit=5)
    raw = {open_ms: (vol, vol_ccy) for open_ms, vol, vol_ccy in _raw_candles(client, SWAP_ID)}

    assert {candle.source for candle in candles} == {"okx_swap"}
    for candle in candles:
        open_ms = str(round(candle.open_time.timestamp() * 1000))
        vol, vol_ccy = raw[open_ms]
        assert candle.volume == Decimal(vol_ccy)
        # 永续的 `vol` 是张数，与标的币数量不同；取错列必然不等。
        assert candle.volume != Decimal(vol)


def test_sources_of_the_two_forms_differ(market: OkxMarketData, timeframe: Timeframe) -> None:
    """同一产品的两种形态各有一行行情，来源标识必须能分开。"""

    spot = market.candles(SPOT_ID, timeframe, inst_type=SPOT, limit=1)[0]
    swap = market.candles(SWAP_ID, timeframe, inst_type=SWAP, limit=1)[0]

    assert spot.source != swap.source
    assert {spot.source, swap.source} == {"okx_spot", "okx_swap"}


def test_daily_candles_open_at_sixteen_utc(market: OkxMarketData, timeframe: Timeframe) -> None:
    for candle in market.candles(SPOT_ID, timeframe, inst_type=SPOT, limit=5):
        assert candle.open_time.tzinfo is not None
        assert int(candle.open_time.timestamp()) % 86400 == 57600


def test_history_candles_page_strictly_before_the_cursor(market: OkxMarketData) -> None:
    hour = Timeframe.parse("1h")
    recent = market.candles(SPOT_ID, hour, inst_type=SPOT, limit=5)
    cursor = recent[0].open_time

    older = market.history_candles(SPOT_ID, hour, inst_type=SPOT, after=cursor, limit=5)

    assert older
    assert all(candle.open_time < cursor for candle in older)
    assert all(candle.confirm for candle in older)


def test_ticker_is_normalised_for_both_types(market: OkxMarketData) -> None:
    for inst_id, inst_type in ((SPOT_ID, SPOT), (SWAP_ID, SWAP)):
        ticker = market.ticker(inst_id, inst_type=inst_type)

        assert ticker.inst_id == inst_id
        assert ticker.bid < ticker.last < ticker.ask
        assert isinstance(ticker.volume_24h, Decimal)
        assert ticker.ts.tzinfo is not None


def test_unknown_type_is_rejected_before_any_request(market: OkxMarketData) -> None:
    hour = Timeframe.parse("1h")

    with pytest.raises(ValidationError, match="FUTURES"):
        market.instruments("FUTURES")
    with pytest.raises(ValidationError, match="FUTURES"):
        market.candles(SPOT_ID, hour, inst_type="FUTURES")


@pytest.mark.parametrize("inst_type", [SPOT, SWAP])
def test_upstream_failure_is_surfaced_for_each_type(
    fake_okx_server: FakeOkxServer, market: OkxMarketData, inst_type: str
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    with pytest.raises(ExchangeError) as caught:
        market.instruments(inst_type)

    assert not isinstance(caught.value, RateLimitedError)


def test_rate_limit_is_surfaced_as_rate_limited_error(
    fake_okx_server: FakeOkxServer, fake_okx_settings: Settings
) -> None:
    fake_okx_server.scenarios.activate("rate_limited")

    with OkxClient(settings=fake_okx_settings) as client, pytest.raises(RateLimitedError):
        client.get(_INSTRUMENTS_PATH, {"instType": SPOT})


def test_upstream_failure_is_surfaced_as_exchange_error(
    fake_okx_server: FakeOkxServer, fake_okx_settings: Settings
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")

    with OkxClient(settings=fake_okx_settings) as client, pytest.raises(ExchangeError) as caught:
        client.get(_INSTRUMENTS_PATH, {"instType": SWAP})

    assert not isinstance(caught.value, RateLimitedError)
