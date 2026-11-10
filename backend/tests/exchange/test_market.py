"""OkxMarketData：字段映射、排序、周期映射与端口契约（零网络）。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.exchange import (
    Candle,
    ExchangeError,
    InstrumentInfo,
    MarketDataPort,
    OkxClient,
    OkxMarketData,
    Ticker,
    create_market_data,
)

SPOT_INSTRUMENT = {
    "instId": "XAAPL-USDT",
    "instType": "SPOT",
    "baseCcy": "AAPL",
    "quoteCcy": "USDT",
    "state": "live",
    "instCategory": "3",
    "tickSz": "0.01",
    "lotSz": "0.001",
    "minSz": "0.01",
    "listTime": "1760000000000",
}

TICKER = {
    "instType": "SPOT",
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
    volume: str = "18.53922",
    confirm: str = "1",
) -> list[str]:
    return [str(ts_ms), open_, high, low, close, volume, volume, volume, confirm]


def test_instruments_requests_spot_only_and_parses_metadata() -> None:
    market, requests = _market(_envelope([SPOT_INSTRUMENT]))

    items = market.instruments()

    assert requests[0].url.path == "/api/v5/public/instruments"
    assert requests[0].url.params["instType"] == "SPOT"
    assert items == [
        InstrumentInfo(
            inst_id="XAAPL-USDT",
            inst_type="SPOT",
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


def test_instruments_missing_list_time_becomes_none() -> None:
    row = {**SPOT_INSTRUMENT, "listTime": ""}
    market, _ = _market(_envelope([row]))

    assert market.instruments()[0].list_time is None
    market.close()


def test_instruments_missing_category_becomes_empty_string() -> None:
    row = {key: value for key, value in SPOT_INSTRUMENT.items() if key != "instCategory"}
    market, _ = _market(_envelope([row]))

    assert market.instruments()[0].inst_category == ""
    market.close()


def test_instruments_row_without_required_field_raises() -> None:
    row = {key: value for key, value in SPOT_INSTRUMENT.items() if key != "instId"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="缺少字段"):
        market.instruments()
    market.close()


def test_instruments_preopen_without_sizes_becomes_none() -> None:
    row = {
        key: value
        for key, value in SPOT_INSTRUMENT.items()
        if key not in {"tickSz", "lotSz", "minSz"}
    }
    row.update({"instId": "XBAC-USDT", "baseCcy": "BAC", "state": "preopen", "tickSz": ""})
    market, _ = _market(_envelope([row]))

    item = market.instruments()[0]

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

    items = market.instruments()

    assert [item.inst_id for item in items] == ["XBAC-USDT", "XAAPL-USDT"]
    assert items[1].tick_size == Decimal("0.01")
    market.close()


def test_instruments_non_object_row_raises() -> None:
    market, _ = _market(_envelope(["not-an-object"]))

    with pytest.raises(ExchangeError, match="结构异常"):
        market.instruments()
    market.close()


def test_instruments_invalid_number_raises() -> None:
    row = {**SPOT_INSTRUMENT, "tickSz": "abc"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="数值非法"):
        market.instruments()
    market.close()


def test_instruments_invalid_list_time_raises() -> None:
    row = {**SPOT_INSTRUMENT, "listTime": "not-a-timestamp"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="时间戳非法"):
        market.instruments()
    market.close()


@pytest.mark.parametrize("bar", ["1h", "1H"])
def test_candles_map_bar_and_return_ascending_from_newest_first(bar: str) -> None:
    newest = _candle_row(1794290400000, close="352.11", confirm="0")
    older = _candle_row(1794286800000, close="351.00", confirm="1")
    market, requests = _market(_envelope([newest, older]))

    candles = market.candles("XAAPL-USDT", bar, limit=2)

    assert requests[0].url.path == "/api/v5/market/candles"
    assert requests[0].url.params["instId"] == "XAAPL-USDT"
    assert requests[0].url.params["bar"] == "1H"
    assert requests[0].url.params["limit"] == "2"
    assert [candle.open_time for candle in candles] == [
        datetime.fromtimestamp(1794286800, tz=UTC),
        datetime.fromtimestamp(1794290400, tz=UTC),
    ]
    assert all(candle.bar == "1h" for candle in candles)
    assert all(candle.source == "okx" for candle in candles)
    assert [candle.confirm for candle in candles] == [True, False]
    assert candles[1] == Candle(
        inst_id="XAAPL-USDT",
        bar="1h",
        open_time=datetime.fromtimestamp(1794290400, tz=UTC),
        open=Decimal("351.62"),
        high=Decimal("352.22"),
        low=Decimal("351.61"),
        close=Decimal("352.11"),
        volume=Decimal("18.53922"),
        confirm=False,
        source="okx",
    )
    market.close()


def test_candles_daily_bar_maps_to_uppercase_d() -> None:
    market, requests = _market(_envelope([_candle_row(1794240000000)]))

    market.candles("XAAPL-USDT", "1d", limit=1)

    assert requests[0].url.params["bar"] == "1D"
    market.close()


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_candles_invalid_limit_raises_before_any_request(limit: int) -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValueError, match="limit"):
        market.candles("XAAPL-USDT", "1h", limit=limit)

    assert requests == []
    market.close()


def test_candles_short_row_raises() -> None:
    market, _ = _market(_envelope([["1794290400000", "1", "2"]]))

    with pytest.raises(ExchangeError, match="K 线数据结构异常"):
        market.candles("XAAPL-USDT", "1h")
    market.close()


def test_candles_non_array_row_raises() -> None:
    market, _ = _market(_envelope([{"ts": "1794290400000"}]))

    with pytest.raises(ExchangeError, match="K 线数据结构异常"):
        market.candles("XAAPL-USDT", "1h")
    market.close()


def test_candles_non_numeric_value_raises() -> None:
    market, _ = _market(_envelope([_candle_row(1794290400000, close="nope")]))

    with pytest.raises(ExchangeError, match="K 线数据非法"):
        market.candles("XAAPL-USDT", "1h")
    market.close()


def test_history_candles_uses_history_path_and_after_cursor() -> None:
    market, requests = _market(_envelope([_candle_row(1794240000000)]))
    after = datetime(2026, 11, 9, tzinfo=UTC)

    market.history_candles("XAAPL-USDT", "1D", after=after, limit=50)

    assert requests[0].url.path == "/api/v5/market/history-candles"
    assert requests[0].url.params["bar"] == "1D"
    assert requests[0].url.params["limit"] == "50"
    assert requests[0].url.params["after"] == str(round(after.timestamp() * 1000))
    market.close()


def test_history_candles_without_cursor_omits_after() -> None:
    market, requests = _market(_envelope([]))

    assert market.history_candles("XAAPL-USDT", "1d") == []
    assert "after" not in requests[0].url.params
    market.close()


def test_history_candles_rejects_naive_cursor() -> None:
    market, requests = _market(_envelope([]))

    with pytest.raises(ValueError, match="时区"):
        market.history_candles("XAAPL-USDT", "1d", after=datetime(2026, 11, 9))

    assert requests == []
    market.close()


def test_ticker_parses_snapshot() -> None:
    market, requests = _market(_envelope([TICKER]))

    ticker = market.ticker("XAAPL-USDT")

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


def test_ticker_empty_data_raises() -> None:
    market, _ = _market(_envelope([]))

    with pytest.raises(ExchangeError, match="为空"):
        market.ticker("XAAPL-USDT")
    market.close()


def test_ticker_missing_field_raises() -> None:
    row = {key: value for key, value in TICKER.items() if key != "last"}
    market, _ = _market(_envelope([row]))

    with pytest.raises(ExchangeError, match="缺少字段"):
        market.ticker("XAAPL-USDT")
    market.close()


def test_ticker_non_object_raises() -> None:
    market, _ = _market(_envelope(["not-an-object"]))

    with pytest.raises(ExchangeError, match="结构异常"):
        market.ticker("XAAPL-USDT")
    market.close()


def test_ticker_invalid_number_raises() -> None:
    market, _ = _market(_envelope([{**TICKER, "last": "abc"}]))

    with pytest.raises(ExchangeError, match="数据非法"):
        market.ticker("XAAPL-USDT")
    market.close()


def test_upstream_error_code_surfaces_as_exchange_error() -> None:
    market, _ = _market({"code": "51001", "msg": "Instrument ID does not exist", "data": []})

    with pytest.raises(ExchangeError) as excinfo:
        market.instruments()

    assert excinfo.value.code == "51001"
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
    assert [item.inst_id for item in port.instruments()] == ["XAAPL-USDT"]
    assert requests[0].url.params["instType"] == "SPOT"
    port.close()


def test_close_releases_underlying_client() -> None:
    market, _ = _market(_envelope([]))

    market.close()

    assert market._client._client.is_closed is True
