"""OkxMarketData：字段映射、排序、周期映射与端口契约（零网络）。

两类标的（`SPOT` / `SWAP`）各走一条正常路径与一条上游错误路径；成交量的取列
口径两类各断言一次，取错列时断言立刻变红。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.core import Bar, InstrumentRef, MarketDataPort, Ticker, Timeframe, ValidationError
from app.exchange import ExchangeError, OkxClient, OkxMarketData, create_market_data

SPOT = "SPOT"
SWAP = "SWAP"

SPOT_INSTRUMENT = {
    "instId": "XAAPL-USDT",
    "instType": SPOT,
    "baseCcy": "AAPL",
    "quoteCcy": "USDT",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.001",
    "minSz": "0.01",
    "listTime": "1760000000000",
}

# 永续行没有 `baseCcy` / `quoteCcy`：标的币种与结算币种分别在 `ctValCcy` / `settleCcy`。
SWAP_INSTRUMENT = {
    "instId": "AAPL-USDT-SWAP",
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

TICKER = {
    "instType": SPOT,
    "instId": "XAAPL-USDT",
    "last": "352.11",
    "lastSz": "1",
    "askPx": "352.22",
    "askSz": "2",
    "bidPx": "352.00",
    "bidSz": "3",
    "open24h": "350",
    "high24h": "355",
    "low24h": "348",
    "vol24h": "1234.5",
    "volCcy24h": "432100",
    "ts": "1794290400000",
    "sodUtc0": "351",
    "sodUtc8": "352",
}

SWAP_TICKER = {
    **TICKER,
    "instType": SWAP,
    "instId": "AAPL-USDT-SWAP",
    "vol24h": "308.625",  # 张数
    "volCcy24h": "1234.5",  # 标的币数量
}


ONE_HOUR = Timeframe.parse("1h")
ONE_DAY = Timeframe.parse("1d")


def _envelope(data: list[Any]) -> dict[str, Any]:
    return {"code": "0", "msg": "", "data": data}


def _market(*payloads: dict[str, Any]) -> tuple[OkxMarketData, list[httpx.Request]]:
    """按调用顺序返回给定应答体的行情实现，并记录发出的请求。"""

    queue = list(payloads)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=queue.pop(0))

    client = OkxClient(
        settings=Settings(okx_rest_base_url="https://okx.test", okx_http_max_retries=0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    return OkxMarketData(client), requests


def _candle_row(
    ts_ms: int,
    *,
    open_: str = "351.62",
    high: str = "352.22",
    low: str = "351.61",
    close: str = "352.11",
    vol: str = "18.53922",
    vol_ccy: str = "6500.00",
    vol_ccy_quote: str = "6510.00",
    confirm: str = "1",
) -> list[str]:
    """上游 K 线行。三列成交量默认取值不同，取错列时断言能看出来。"""

    return [str(ts_ms), open_, high, low, close, vol, vol_ccy, vol_ccy_quote, confirm]


def test_instruments_request_the_requested_type_only() -> None:
    market, requests = _market(_envelope([SWAP_INSTRUMENT]))

    market.instruments(SWAP)

    assert requests[0].url.path == "/api/v5/public/instruments"
    assert requests[0].url.params["instType"] == SWAP
    market.close()


def test_instruments_parse_spot_metadata() -> None:
    market, _ = _market(_envelope([SPOT_INSTRUMENT]))

    items = market.instruments(SPOT)

    assert items == [
        InstrumentRef(
            inst_id="XAAPL-USDT",
            inst_type=SPOT,
            base_ccy="AAPL",
            quote_ccy="USDT",
            state="live",
            inst_category="3",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.001"),
            min_size=Decimal("0.01"),
            list_time=datetime.fromtimestamp(1760000000, tz=UTC),
        )
    ]
    market.close()


def test_instruments_parse_swap_metadata_with_currency_fallback() -> None:
    market, _ = _market(_envelope([SWAP_INSTRUMENT]))

    items = market.instruments(SWAP)

    assert items == [
        InstrumentRef(
            inst_id="AAPL-USDT-SWAP",
            inst_type=SWAP,
            base_ccy="AAPL",
            quote_ccy="USDT",
            state="live",
            inst_category="3",
            tick_size=Decimal("0.01"),
            lot_size=Decimal("0.1"),
            min_size=Decimal("0.1"),
            list_time=datetime.fromtimestamp(1760000000, tz=UTC),
            ct_val_ccy="AAPL",
            settle_ccy="USDT",
            ct_val=Decimal("1"),
            ct_mult=Decimal("1"),
            ct_type="linear",
            max_lever=Decimal("20"),
        )
    ]
    market.close()


def test_instruments_normalise_the_type_spelling() -> None:
    market, requests = _market(_envelope([]))

    market.instruments(" swap ")

    assert requests[0].url.params["instType"] == SWAP
    market.close()


def test_instruments_reject_unknown_type_before_any_request() -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValidationError, match="FUTURES"):
        market.instruments("FUTURES")

    assert requests == []
    market.close()


def test_instruments_business_error_surfaces_for_each_type() -> None:
    for inst_type in (SPOT, SWAP):
        market, _ = _market({"code": "51001", "msg": "Instrument ID does not exist", "data": []})

        with pytest.raises(ExchangeError) as excinfo:
            market.instruments(inst_type)

        assert excinfo.value.code == "51001"
        market.close()


def test_instruments_missing_list_time_becomes_none() -> None:
    row = {**SPOT_INSTRUMENT, "listTime": ""}
    market, _ = _market(_envelope([row]))

    assert market.instruments(SPOT)[0].list_time is None
    market.close()


def test_instruments_missing_category_becomes_empty_string() -> None:
    row = {key: value for key, value in SPOT_INSTRUMENT.items() if key != "instCategory"}
    market, _ = _market(_envelope([row]))

    assert market.instruments(SPOT)[0].inst_category == ""
    market.close()


def test_instruments_row_without_required_field_raises() -> None:
    row = {key: value for key, value in SPOT_INSTRUMENT.items() if key != "instId"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="缺少字段"):
        market.instruments(SPOT)
    market.close()


def test_instruments_unknown_inst_type_in_row_raises() -> None:
    row = {**SPOT_INSTRUMENT, "instType": "FUTURES"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="币种字段映射"):
        market.instruments(SPOT)
    market.close()


def test_instruments_preopen_without_sizes_becomes_none() -> None:
    row = {
        key: value
        for key, value in SPOT_INSTRUMENT.items()
        if key not in {"tickSz", "lotSz", "minSz"}
    }
    row.update({"instId": "XBAC-USDT", "baseCcy": "BAC", "state": "preopen", "tickSz": ""})
    market, _ = _market(_envelope([row]))

    item = market.instruments(SPOT)[0]

    assert (item.state, item.tick_size, item.lot_size, item.min_size) == (
        "preopen",
        None,
        None,
        None,
    )
    assert item.inst_category == "3"
    market.close()


def test_instruments_preopen_row_does_not_drop_whole_batch() -> None:
    preopen = {**SPOT_INSTRUMENT, "instId": "XBAC-USDT", "state": "preopen"}
    preopen.update({"tickSz": "", "lotSz": "", "minSz": ""})
    market, _ = _market(_envelope([preopen, SPOT_INSTRUMENT]))

    items = market.instruments(SPOT)

    assert [item.inst_id for item in items] == ["XBAC-USDT", "XAAPL-USDT"]
    assert items[1].tick_size == Decimal("0.01")
    market.close()


def test_instruments_non_object_row_raises() -> None:
    market, _ = _market(_envelope(["not-an-object"]))

    with pytest.raises(ExchangeError, match="结构异常"):
        market.instruments(SPOT)
    market.close()


def test_instruments_invalid_number_raises() -> None:
    row = {**SPOT_INSTRUMENT, "tickSz": "abc"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="数值非法"):
        market.instruments(SPOT)
    market.close()


def test_instruments_invalid_list_time_raises() -> None:
    row = {**SPOT_INSTRUMENT, "listTime": "not-a-timestamp"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="时间戳非法"):
        market.instruments(SPOT)
    market.close()


def test_candles_map_timeframe_and_return_ascending_from_newest_first() -> None:
    newest = _candle_row(1794290400000, close="352.11", confirm="0")
    older = _candle_row(1794286800000, close="351.00", confirm="1")
    market, requests = _market(_envelope([newest, older]))

    candles = market.candles("XAAPL-USDT", ONE_HOUR, inst_type=SPOT, limit=2)

    assert requests[0].url.path == "/api/v5/market/candles"
    assert requests[0].url.params["instId"] == "XAAPL-USDT"
    assert requests[0].url.params["bar"] == "1H"
    assert requests[0].url.params["limit"] == "2"
    assert [candle.open_time for candle in candles] == [
        datetime.fromtimestamp(1794286800, tz=UTC),
        datetime.fromtimestamp(1794290400, tz=UTC),
    ]
    assert all(candle.timeframe == ONE_HOUR for candle in candles)
    assert all(candle.source == "okx_spot" for candle in candles)
    assert [candle.confirm for candle in candles] == [True, False]
    assert candles[1] == Bar(
        inst_id="XAAPL-USDT",
        timeframe=ONE_HOUR,
        open_time=datetime.fromtimestamp(1794290400, tz=UTC),
        open=Decimal("351.62"),
        high=Decimal("352.22"),
        low=Decimal("351.61"),
        close=Decimal("352.11"),
        volume=Decimal("18.53922"),
        confirm=False,
        source="okx_spot",
    )
    market.close()


def test_candles_spot_take_volume_from_the_vol_column() -> None:
    """现货的 `vol` 就是标的币数量；`volCcy` 是计价额，不能当成交量。"""

    row = _candle_row(1794290400000, vol="18.5", vol_ccy="6500.00", vol_ccy_quote="6500.00")
    market, _ = _market(_envelope([row]))

    candle = market.candles("XAAPL-USDT", ONE_HOUR, inst_type=SPOT, limit=1)[0]

    assert candle.volume == Decimal("18.5")
    assert candle.source == "okx_spot"
    market.close()


def test_candles_swap_take_volume_from_the_vol_ccy_column() -> None:
    """永续的 `vol` 是张数；标的币数量在 `volCcy`。"""

    row = _candle_row(1794290400000, vol="4.625", vol_ccy="18.5", vol_ccy_quote="6500.00")
    market, _ = _market(_envelope([row]))

    candle = market.candles("AAPL-USDT-SWAP", ONE_HOUR, inst_type=SWAP, limit=1)[0]

    assert candle.volume == Decimal("18.5")
    assert candle.source == "okx_swap"
    market.close()


def test_candles_sources_of_the_two_forms_differ() -> None:
    """同一产品两种形态：来源标识不同，落库后才能按来源分开取数。"""

    spot_market, _ = _market(_envelope([_candle_row(1794290400000)]))
    swap_market, _ = _market(_envelope([_candle_row(1794290400000)]))

    spot = spot_market.candles("XAAPL-USDT", ONE_HOUR, inst_type=SPOT, limit=1)[0]
    swap = swap_market.candles("AAPL-USDT-SWAP", ONE_HOUR, inst_type=SWAP, limit=1)[0]

    assert (spot.source, swap.source) == ("okx_spot", "okx_swap")
    spot_market.close()
    swap_market.close()


def test_candles_daily_bar_maps_to_uppercase_d() -> None:
    market, requests = _market(_envelope([_candle_row(1794240000000)]))

    market.candles("XAAPL-USDT", ONE_DAY, inst_type=SPOT, limit=1)

    assert requests[0].url.params["bar"] == "1D"
    market.close()


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_candles_invalid_limit_raises_before_any_request(limit: int) -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValueError, match="limit"):
        market.candles("XAAPL-USDT", ONE_HOUR, inst_type=SPOT, limit=limit)

    assert requests == []
    market.close()


def test_candles_reject_unknown_type_before_any_request() -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValidationError, match="FUTURES"):
        market.candles("XAAPL-USDT", ONE_HOUR, inst_type="FUTURES")

    assert requests == []
    market.close()


@pytest.mark.parametrize("inst_type", [SPOT, SWAP])
def test_candles_short_row_raises(inst_type: str) -> None:
    market, _ = _market(_envelope([["1794290400000", "1", "2"]]))

    with pytest.raises(ExchangeError, match="K 线数据结构异常"):
        market.candles("XAAPL-USDT", ONE_HOUR, inst_type=inst_type)
    market.close()


def test_candles_non_array_row_raises() -> None:
    market, _ = _market(_envelope([{"ts": "1794290400000"}]))

    with pytest.raises(ExchangeError, match="K 线数据结构异常"):
        market.candles("XAAPL-USDT", ONE_HOUR, inst_type=SPOT)
    market.close()


@pytest.mark.parametrize("inst_type", [SPOT, SWAP])
def test_candles_non_numeric_value_raises(inst_type: str) -> None:
    market, _ = _market(_envelope([_candle_row(1794290400000, close="nope")]))

    with pytest.raises(ExchangeError, match="K 线数据非法"):
        market.candles("XAAPL-USDT", ONE_HOUR, inst_type=inst_type)
    market.close()


def test_history_candles_uses_history_path_and_after_cursor() -> None:
    market, requests = _market(_envelope([_candle_row(1794240000000)]))
    after = datetime(2026, 11, 9, tzinfo=UTC)

    market.history_candles("XAAPL-USDT", ONE_DAY, inst_type=SPOT, after=after, limit=50)

    assert requests[0].url.path == "/api/v5/market/history-candles"
    assert requests[0].url.params["bar"] == "1D"
    assert requests[0].url.params["limit"] == "50"
    assert requests[0].url.params["after"] == str(round(after.timestamp() * 1000))
    market.close()


def test_history_candles_without_cursor_omits_after() -> None:
    market, requests = _market(_envelope([]))

    assert market.history_candles("XAAPL-USDT", ONE_DAY, inst_type=SPOT) == []
    assert "after" not in requests[0].url.params
    market.close()


def test_history_candles_rejects_naive_cursor() -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValueError, match="时区"):
        market.history_candles("XAAPL-USDT", ONE_DAY, inst_type=SPOT, after=datetime(2026, 11, 9))

    assert requests == []
    market.close()


def test_ticker_parses_snapshot() -> None:
    market, requests = _market(_envelope([TICKER]))

    ticker = market.ticker("XAAPL-USDT", inst_type=SPOT)

    assert requests[0].url.path == "/api/v5/market/ticker"
    assert requests[0].url.params["instId"] == "XAAPL-USDT"
    assert ticker == Ticker(
        inst_id="XAAPL-USDT",
        last=Decimal("352.11"),
        bid=Decimal("352.00"),
        ask=Decimal("352.22"),
        volume_24h=Decimal("1234.5"),
        ts=datetime.fromtimestamp(1794290400, tz=UTC),
    )
    market.close()


def test_ticker_swap_takes_volume_from_vol_ccy_24h() -> None:
    market, _ = _market(_envelope([SWAP_TICKER]))

    ticker = market.ticker("AAPL-USDT-SWAP", inst_type=SWAP)

    assert ticker.volume_24h == Decimal("1234.5")
    market.close()


@pytest.mark.parametrize("inst_type", [SPOT, SWAP])
def test_ticker_business_error_surfaces_as_exchange_error(inst_type: str) -> None:
    market, _ = _market({"code": "51001", "msg": "Instrument ID does not exist", "data": []})

    with pytest.raises(ExchangeError):
        market.ticker("XAAPL-USDT", inst_type=inst_type)
    market.close()


def test_ticker_empty_data_raises() -> None:
    market, _ = _market(_envelope([]))

    with pytest.raises(ExchangeError, match="为空"):
        market.ticker("XAAPL-USDT", inst_type=SPOT)
    market.close()


def test_ticker_missing_field_raises() -> None:
    row = {key: value for key, value in TICKER.items() if key != "last"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="缺少字段"):
        market.ticker("XAAPL-USDT", inst_type=SPOT)
    market.close()


def test_ticker_non_object_raises() -> None:
    market, _ = _market(_envelope(["not-an-object"]))

    with pytest.raises(ExchangeError, match="结构异常"):
        market.ticker("XAAPL-USDT", inst_type=SPOT)
    market.close()


def test_ticker_invalid_number_raises() -> None:
    market, _ = _market(_envelope([{**TICKER, "last": "abc"}]))

    with pytest.raises(ExchangeError, match="数据非法"):
        market.ticker("XAAPL-USDT", inst_type=SPOT)
    market.close()


def test_implementation_satisfies_market_data_port() -> None:
    market, _ = _market(_envelope([]))

    assert isinstance(market, MarketDataPort)
    market.close()


def test_create_market_data_wires_default_settings_through_transport() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_envelope([SPOT_INSTRUMENT]))

    port = create_market_data(transport=httpx.MockTransport(handler))

    assert isinstance(port, OkxMarketData)
    assert isinstance(port, MarketDataPort)
    assert [item.inst_id for item in port.instruments(SPOT)] == ["XAAPL-USDT"]
    assert requests[0].url.params["instType"] == "SPOT"
    port.close()


def test_close_releases_underlying_client() -> None:
    market, _ = _market(_envelope([]))

    market.close()

    assert market._client._client.is_closed is True
