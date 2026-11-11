"""美股代理行情源：日线取数、复权口径、周期能力声明与落库后的来源共存。

全部用例零网络：上游是 `tests/fakes/equity` 的假行情，经 `httpx.MockTransport`
直连。正常路径与错误路径各有用例；「只能日线」这条能力声明与它的拒绝行为成对
断言——只声明不拒绝，或只拒绝不声明，都会让 T1.7 的来源选择落空。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import (
    Bar,
    DataUnavailable,
    MarketDataPort,
    Timeframe,
    UpstreamError,
    ValidationError,
    get,
    list_names,
)
from app.db import init_db
from app.exchange import ExchangeError
from app.exchange.providers import create_us_equity_market_data
from app.exchange.providers.us_equity import SOURCE, SUPPORTED_TIMEFRAMES, UsEquityMarketData
from app.instrument import sync_instruments
from app.market import load_candles, sync_candles, upsert_candles
from tests.factories.instruments import make_ref
from tests.fakes.equity.service import EquityScenario, chart_handler
from tests.fakes.equity.store import FakeEquity

# 代理源的标识口径：OKX 上这个产品的现货标识。库里 proxy 与 okx_spot 两种来源
# 都写在这一行标的下，主键靠 `source` 区分。
SYMBOL = "XAAPL-USDT"
TICKER = "AAPL"
ONE_DAY = Timeframe.parse("1d")
# 价格精度：与适配层的收敛精度一致；契约上限是 12 位小数，这里断言比它更紧。
_PRICE_QUANTUM = Decimal("0.0001")
_PRICE_DECIMALS = 4
_FROM = datetime(2026, 10, 1, tzinfo=UTC)
_TO = datetime(2026, 11, 12, tzinfo=UTC)


def _settings() -> Settings:
    """测试配置：上游地址指向假服务，超时与生产同形。"""

    return Settings(
        us_equity_rest_base_url="https://equity.test",
        us_equity_http_timeout_seconds=5,
    )


def _port(
    equity: FakeEquity,
    *,
    requests: list[httpx.Request] | None = None,
    scenario: EquityScenario | None = None,
    transport: httpx.BaseTransport | None = None,
) -> UsEquityMarketData:
    """装配被测实现；`ticker_of` 换成固定映射，用例不连标的表。"""

    return UsEquityMarketData(
        settings=_settings(),
        transport=transport
        or httpx.MockTransport(chart_handler(equity, requests=requests, scenario=scenario)),
        ticker_of=_fixed_mapping,
    )


def _fixed_mapping(inst_id: str) -> str:
    """OKX 标识 → 美股代码的固定映射；未登记的标识返回空串（适配器必须拒绝）。"""

    return TICKER if inst_id == SYMBOL else ""


@pytest.fixture()
def equity() -> FakeEquity:
    """十根已完成日线，最后一根在 2026-11-10（周二）。"""

    return FakeEquity(ticker=TICKER, count=10)


@pytest.fixture()
def schema() -> None:
    """落库相关的用例先建表：schema 由根 conftest 隔离，这里只执行迁移。"""

    init_db()


# ------------------------------------------------------------------ 周期能力声明


def test_supported_timeframes_are_daily_only(equity: FakeEquity) -> None:
    """能力声明只有一个周期：日线。声明与拒绝必须成对，缺一半都不可用。"""

    port = _port(equity)

    assert port.supported_timeframes() == (ONE_DAY,)
    assert SUPPORTED_TIMEFRAMES == (ONE_DAY,)
    port.close()


@pytest.mark.parametrize("raw_bar", ["1m", "5m", "15m", "1h", "4h"])
def test_intraday_timeframe_is_rejected_without_a_request(equity: FakeEquity, raw_bar: str) -> None:
    """日内周期一律拒绝，且在发出任何请求之前就拒绝。"""

    requests: list[httpx.Request] = []
    port = _port(equity, requests=requests)
    timeframe = Timeframe.parse(raw_bar)

    with pytest.raises(ValidationError):
        port.candles(SYMBOL, timeframe, inst_type="SPOT")
    with pytest.raises(ValidationError):
        port.history_candles(SYMBOL, timeframe, inst_type="SPOT", limit=10)

    assert requests == []
    port.close()


def test_unknown_category_is_rejected_before_a_request(equity: FakeEquity) -> None:
    """未登记的类别按参数不合法处理，不退回另一类口径，也不发请求。"""

    requests: list[httpx.Request] = []
    port = _port(equity, requests=requests)

    with pytest.raises(ValidationError):
        port.history_candles(SYMBOL, ONE_DAY, inst_type="FUTURES", limit=5)

    assert requests == []
    port.close()


# ------------------------------------------------------------------ 日线取数


def test_daily_candles_use_the_adjusted_close(equity: FakeEquity) -> None:
    """收盘价取复权列：与原始收盘价不同，取错列时断言立刻变红。"""

    port = _port(equity)

    bars = port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=10)

    assert len(bars) == 10
    assert all(isinstance(bar, Bar) for bar in bars)
    assert [bar.open_time for bar in bars] == sorted(bar.open_time for bar in bars)
    envelope = FakeEquity(ticker=TICKER, count=1).chart(
        period1=equity.open_times[-1], period2=equity.open_times[-1] + 1
    )
    indicators = envelope["chart"]["result"][0]["indicators"]
    raw_close = Decimal(str(indicators["quote"][0]["close"][0]))
    adjusted_close = Decimal(str(indicators["adjclose"][0]["adjclose"][0]))
    last = bars[-1]
    # 两列在夹具里刻意不同：取了原始收盘价立刻变红。
    assert last.close != raw_close.quantize(_PRICE_QUANTUM)
    assert last.close == adjusted_close.quantize(_PRICE_QUANTUM)
    port.close()


def test_prices_fit_the_price_precision_before_they_are_stored(equity: FakeEquity) -> None:
    """上游是 float32 形态的 13-14 位小数：解析后必须收敛到价格精度。

    不收敛就会带着二进制噪声入库，超过契约 `DecimalString` 的 12 位上限，K 线接口
    序列化时 500（见 `test_proxy_rows_are_readable_through_the_candles_api`）。
    """

    port = _port(equity)

    bars = port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=10)

    for bar in bars:
        for value in (bar.open, bar.high, bar.low, bar.close):
            assert -value.as_tuple().exponent <= _PRICE_DECIMALS, value
        assert bar.volume == bar.volume.to_integral_value(), bar.volume
    port.close()


def test_daily_candles_request_the_events_needed_for_adjustment(equity: FakeEquity) -> None:
    """请求带 `events=div,splits` 与 `includeAdjustedClose`：复权数据由上游给出。"""

    requests: list[httpx.Request] = []
    port = _port(equity, requests=requests)

    port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=5)

    assert len(requests) == 1
    params = requests[0].url.params
    assert requests[0].url.path == "/v8/finance/chart/AAPL"
    assert params["interval"] == "1d"
    assert params["events"] == "div,splits"
    assert params["includeAdjustedClose"] == "true"
    assert int(params["period1"]) < int(params["period2"])
    port.close()


def test_dividends_and_splits_only_confirm_the_adjustment(equity: FakeEquity) -> None:
    """有分红/拆股时不自行换算：带事件与不带事件的收盘价逐根相同。"""

    with_events = _port(equity).candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=10)
    without_events = _port(FakeEquity(ticker=TICKER, count=10, with_events=False)).candles(
        SYMBOL, ONE_DAY, inst_type="SPOT", limit=10
    )

    assert [bar.close for bar in with_events] == [bar.close for bar in without_events]
    assert len(with_events) == 10


def test_history_candles_stop_before_the_cursor(equity: FakeEquity) -> None:
    """`after` 是分页游标：这一页全部早于它，且是最靠近它的那一批。"""

    port = _port(equity)
    cursor = datetime.fromtimestamp(equity.open_times[-3], tz=UTC)

    older = port.history_candles(SYMBOL, ONE_DAY, inst_type="SPOT", after=cursor, limit=2)

    assert [bar.open_time for bar in older] == [
        datetime.fromtimestamp(equity.open_times[-5], tz=UTC),
        datetime.fromtimestamp(equity.open_times[-4], tz=UTC),
    ]
    port.close()


def test_history_without_a_cursor_matches_the_latest_candles(equity: FakeEquity) -> None:
    """没有游标时与 `candles` 同一口径：都返回最近的一段。"""

    port = _port(equity)

    assert port.history_candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=4) == port.candles(
        SYMBOL, ONE_DAY, inst_type="SPOT", limit=4
    )
    port.close()


def test_an_unfinished_bar_is_flagged() -> None:
    """盘中最后一根还没收盘：标成未收盘，落库时由写入路径丢弃。"""

    port = _port(FakeEquity(ticker=TICKER, count=3, in_session=True))

    bars = port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3)

    assert [bar.confirm for bar in bars] == [True, True, False]
    port.close()


def test_empty_window_is_an_empty_result_not_an_error() -> None:
    """窗口里没有行情就是空列表：翻页到尽头靠这个信号结束，不能抛错。"""

    port = _port(FakeEquity(ticker=TICKER, count=3))

    assert (
        port.history_candles(
            SYMBOL, ONE_DAY, inst_type="SPOT", after=datetime(2000, 1, 1, tzinfo=UTC), limit=3
        )
        == []
    )
    port.close()


# ------------------------------------------------------------------ 边界：只做历史日线


def test_instruments_are_not_published_by_the_proxy(equity: FakeEquity) -> None:
    """代理标的不进入可交易集合：不下发标的元数据，也不写标的表。"""

    port = _port(equity)

    with pytest.raises(DataUnavailable):
        port.instruments("SPOT")
    port.close()


def test_ticker_is_not_implemented(equity: FakeEquity) -> None:
    """不实现实时行情：要快照就报「本来源不提供」，不返回伪造的收盘价。"""

    port = _port(equity)

    with pytest.raises(DataUnavailable):
        port.ticker(SYMBOL, inst_type="SPOT")
    port.close()


# ------------------------------------------------------------------ 上游错误


def test_http_error_becomes_an_upstream_error(equity: FakeEquity) -> None:
    port = _port(equity, scenario=EquityScenario(status_code=500, body={"error": "boom"}))

    with pytest.raises(UpstreamError):
        port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=5)
    port.close()


def test_transport_error_becomes_an_upstream_error(equity: FakeEquity) -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("拒绝连接", request=request)

    port = _port(equity, transport=httpx.MockTransport(failing))

    with pytest.raises(UpstreamError):
        port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=5)
    port.close()


def test_upstream_error_payload_becomes_an_upstream_error() -> None:
    """上游 HTTP 200 但 `chart.error` 有内容：按上游故障处理，不当成空结果。"""

    port = _port(FakeEquity(ticker="MSFT", count=3))

    with pytest.raises(ExchangeError):
        port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3)
    port.close()


def test_events_without_adjusted_close_are_rejected() -> None:
    """有分红/拆股却没给复权收盘价：无法保证复权口径，直接报上游数据不可用。"""

    port = _port(FakeEquity(ticker=TICKER, count=3, with_adjusted_close=False))

    with pytest.raises(ExchangeError):
        port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3)
    port.close()


# 上游 HTTP 200 但应答形状不对：每一种都要收敛成 `ExchangeError`，不能漏出
# `AttributeError` / `TypeError` 这类裸异常——否则调用方按上游故障分派会失效。
_MALFORMED_PAYLOADS: dict[str, Callable[[dict[str, Any]], None]] = {
    "timestamp_not_a_list": lambda result: result.update(timestamp="oops"),
    "indicators_not_a_dict": lambda result: result.update(indicators="oops"),
    "quote_missing": lambda result: result.update(indicators={}),
    "quote_not_a_list": lambda result: result.update(indicators={"quote": "oops"}),
    "quote_entry_not_a_dict": lambda result: result.update(indicators={"quote": ["oops"]}),
    "adjclose_not_a_dict": lambda result: result["indicators"].update(adjclose="oops"),
    "adjclose_missing": lambda result: result["indicators"].pop("adjclose"),
    "adjclose_not_a_list": lambda result: result["indicators"]["adjclose"][0].update(
        adjclose="oops"
    ),
}


@pytest.mark.parametrize("corrupt", _MALFORMED_PAYLOADS.values(), ids=_MALFORMED_PAYLOADS.keys())
def test_malformed_payload_becomes_an_upstream_error(
    equity: FakeEquity, corrupt: Callable[[dict[str, Any]], None]
) -> None:
    """形状异常与 HTTP 错误、上游报错走同一条收敛路径。"""

    envelope = equity.chart(period1=0, period2=2**31)
    corrupt(envelope["chart"]["result"][0])
    port = _port(equity, scenario=EquityScenario(status_code=200, body=envelope))

    with pytest.raises(ExchangeError):
        port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=5)
    port.close()


def test_the_ticker_mapping_is_resolved_once_per_symbol(equity: FakeEquity) -> None:
    """一次同步要翻很多页：同一标的只解析一次美股代码，不重复查标的表。"""

    calls: list[str] = []

    def resolve(inst_id: str) -> str:
        calls.append(inst_id)
        return TICKER

    port = UsEquityMarketData(
        settings=_settings(),
        transport=httpx.MockTransport(chart_handler(equity)),
        ticker_of=resolve,
    )

    for _ in range(3):
        assert port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3)

    assert calls == [SYMBOL]
    port.close()


def test_unknown_symbol_has_no_ticker_mapping() -> None:
    """映射缺失是调用方错误：报参数不合法，不发请求去猜代码。"""

    requests: list[httpx.Request] = []
    equity = FakeEquity(ticker=TICKER, count=3)
    port = UsEquityMarketData(
        settings=_settings(),
        transport=httpx.MockTransport(chart_handler(equity, requests=requests)),
        ticker_of=_fixed_mapping,
    )

    with pytest.raises(ValidationError):
        port.candles("XZZZZ-USDT", ONE_DAY, inst_type="SPOT", limit=3)

    assert requests == []
    port.close()


# ------------------------------------------------------------------ 端口与注册


def test_satisfies_the_market_data_port(equity: FakeEquity) -> None:
    assert isinstance(_port(equity), MarketDataPort)


def test_registry_holds_the_provider_factory() -> None:
    """注册条目是装配方按名字取用的入口：import 即登记，不写目录扫描。"""

    assert SOURCE == "us_equity_proxy"
    assert get("provider", SOURCE) is create_us_equity_market_data
    assert SOURCE in list_names("provider")


def test_the_default_ticker_mapping_comes_from_the_instrument_table(schema: None) -> None:
    """默认映射查标的表：配对关系由标的模块维护，适配层不拆字符串。"""

    sync_instruments([make_ref()])
    equity = FakeEquity(ticker=TICKER, count=3)
    port = create_us_equity_market_data(
        settings=_settings(), transport=httpx.MockTransport(chart_handler(equity))
    )

    assert len(port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3)) == 3
    with pytest.raises(ValidationError):
        port.candles("XZZZZ-USDT", ONE_DAY, inst_type="SPOT", limit=3)
    port.close()


def test_proxy_rows_are_readable_through_the_candles_api(
    equity: FakeEquity, client: TestClient
) -> None:
    """代理日线落库后必须能按来源读回：价格精度不收敛时接口会 500（功能检测 F1）。"""

    sync_instruments([make_ref()])
    port = _port(equity)
    upsert_candles(port.candles(SYMBOL, ONE_DAY, inst_type="SPOT", limit=3))

    response = client.get(
        f"/api/instruments/{SYMBOL}/candles", params={"bar": "1d", "source": SOURCE}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == SOURCE
    assert len(body["candles"]) == 3
    port.close()


# ------------------------------------------------------------------ 落库：两种来源共存


def _spot_bar(open_time: datetime) -> Bar:
    """OKX 侧的一根日线：与代理源同一标的、同一开盘时刻，只有来源不同。"""

    return Bar(
        inst_id=SYMBOL,
        timeframe=ONE_DAY,
        open_time=open_time,
        open=Decimal("352.10"),
        high=Decimal("353.00"),
        low=Decimal("351.00"),
        close=Decimal("352.50"),
        volume=Decimal("1000"),
        confirm=True,
        source="okx_spot",
    )


@pytest.fixture()
def synced_proxy(equity: FakeEquity, schema: None) -> Iterator[UsEquityMarketData]:
    """把假行情的日线按生产写入路径落到 `candles`（代理来源）。"""

    port = _port(equity)
    sync_candles(
        port,
        SYMBOL,
        "1d",
        _FROM,
        _TO,
        inst_type="SPOT",
        asset_type="tokenized_equity",
        source=SOURCE,
    )
    yield port
    port.close()


def test_proxy_and_okx_rows_coexist_under_one_key(synced_proxy: UsEquityMarketData) -> None:
    """同一 (symbol, bar, open_time) 在两种来源下各一行，主键不冲突。"""

    proxy_rows = load_candles(SYMBOL, "1d", source=SOURCE)
    open_time = proxy_rows[-1].open_time
    upsert_candles([_spot_bar(open_time)])

    assert len(proxy_rows) == 10
    okx_rows = load_candles(SYMBOL, "1d", source="okx_spot")
    assert len(okx_rows) == 1
    assert okx_rows[0].open_time == open_time
    assert {row.source for row in load_candles(SYMBOL, "1d")} == {SOURCE, "okx_spot"}


def test_synced_proxy_rows_carry_the_daily_open_of_the_us_session(
    synced_proxy: UsEquityMarketData,
) -> None:
    """代理日线的开盘时刻来自上游（美东 09:30），不是 OKX 的 UTC+8 零点。"""

    rows = load_candles(SYMBOL, "1d", source=SOURCE)
    opens = [row.open_time for row in rows]

    assert [row.source for row in rows] == [SOURCE] * len(rows)
    assert opens[0] == datetime.fromtimestamp(
        FakeEquity(ticker=TICKER, count=10).open_times[0], tz=UTC
    )
    assert {moment.hour for moment in opens} == {14}  # 冬令时：09:30 美东 = 14:30 UTC
    # 交易日之间只可能是相邻一天或跨周末三天。
    assert {later - earlier for earlier, later in pairwise(opens)} == {
        timedelta(days=1),
        timedelta(days=3),
    }
