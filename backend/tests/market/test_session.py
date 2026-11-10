"""市场时段与数据来源治理：资产时段、交易所时段、来源优先级、跨源偏离与日界定界。

时段是纯函数，全部用「已知答案」断言：每个边界的当刻、前一分钟、后一分钟各一条；
节假日用真实休市日；跨源偏离用固定价格构造，不依赖当前时间。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core import Bar, Timeframe, ValidationError
from app.db import session_scope
from app.instrument import sync_instruments
from app.market import (
    DEFAULT_THRESHOLD_PCT,
    EXCHANGE_CLOSED,
    EXCHANGE_OPEN,
    SESSION_CLOSED,
    SESSION_POST,
    SESSION_PRE,
    SESSION_REGULAR,
    DivergenceAlert,
    Quote,
    asset_session,
    current_bar,
    daily_open_time,
    divergence,
    exchange_session,
    integrity,
    is_trading_day,
    load_candles,
    primary_source,
    sync_candles,
    upsert_candles,
)
from tests.factories.instruments import make_ref, make_swap_ref

EASTERN = ZoneInfo("America/New_York")

CRYPTO = "crypto"
TOKENIZED_EQUITY = "tokenized_equity"
COMMODITY_TOKEN = "commodity_token"
UNKNOWN_ASSET = "unknown"

# 正常交易日（周三，美东时间，冬令时 UTC-5）；四个时段边界都落在这天。
TRADING_DAY = date(2026, 11, 25)

# 已知休市日：感恩节、圣诞、独立日观察日（7/4 是周六）、2025 年感恩节。
KNOWN_HOLIDAYS = (
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2026, 7, 3),
    date(2025, 11, 27),
)


def _et(day: date, hour: int, minute: int) -> datetime:
    """美东当地时间（冬令时 UTC-5 / 夏令时 UTC-4 由时区库判断）。"""

    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=EASTERN)


# --------------------------------------------------------------- 资产时段边界


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        # 盘前 04:00 开盘
        (3, 59, SESSION_CLOSED),
        (4, 0, SESSION_PRE),
        (4, 1, SESSION_PRE),
        # 正常时段 09:30 开盘
        (9, 29, SESSION_PRE),
        (9, 30, SESSION_REGULAR),
        (9, 31, SESSION_REGULAR),
        # 正常时段 16:00 收盘
        (15, 59, SESSION_REGULAR),
        (16, 0, SESSION_POST),
        (16, 1, SESSION_POST),
        # 盘后 20:00 收盘
        (19, 59, SESSION_POST),
        (20, 0, SESSION_CLOSED),
        (20, 1, SESSION_CLOSED),
    ],
)
def test_tokenized_equity_session_boundaries(hour: int, minute: int, expected: str) -> None:
    """四个资产时段边界的前一分钟、边界当刻、后一分钟各一条已知答案。"""

    assert asset_session(TOKENIZED_EQUITY, _et(TRADING_DAY, hour, minute)) == expected


def test_crypto_never_leaves_the_trading_session() -> None:
    """加密资产 24/7：跨越周末与感恩节逐刻采样，没有一刻被判为休市。"""

    start = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
    samples = [start + timedelta(minutes=15 * step) for step in range(4 * 24 * 4)]
    sessions = {asset_session(CRYPTO, moment) for moment in samples}

    assert sessions == {SESSION_REGULAR}


def test_tokenized_equity_is_closed_on_the_weekend_and_on_holidays() -> None:
    """周末与已知休市日的任何时点都不属于交易时段。"""

    for holiday in KNOWN_HOLIDAYS:
        for hour in (5, 10, 17, 23):
            assert asset_session(TOKENIZED_EQUITY, _et(holiday, hour, 0)) == SESSION_CLOSED

    for weekend in (date(2026, 11, 28), date(2026, 11, 29)):
        assert asset_session(TOKENIZED_EQUITY, _et(weekend, 12, 0)) == SESSION_CLOSED


def test_unknown_and_commodity_asset_types_follow_the_equity_calendar() -> None:
    """`commodity_token` 与 `unknown` 暂按代币化股票的时段处理（临时取值）。"""

    for asset_type in (COMMODITY_TOKEN, UNKNOWN_ASSET):
        assert asset_session(asset_type, _et(TRADING_DAY, 12, 0)) == SESSION_REGULAR
        assert asset_session(asset_type, _et(KNOWN_HOLIDAYS[0], 12, 0)) == SESSION_CLOSED


def test_crypto_spot_and_perpetual_are_both_in_session_when_the_us_market_closes() -> None:
    """加密现货与加密永续在美股休市时刻都判为交易中：类别不决定时段，资产才决定。"""

    moment = _et(KNOWN_HOLIDAYS[0], 12, 0)

    assert asset_session(CRYPTO, moment, inst_type="SPOT") == SESSION_REGULAR
    assert asset_session(CRYPTO, moment, inst_type="SWAP") == SESSION_REGULAR
    # 同一时刻同一类别里，代币化股票永续是休市——差别来自资产，不来自 `SWAP`。
    assert asset_session(TOKENIZED_EQUITY, moment, inst_type="SWAP") == SESSION_CLOSED


def test_asset_type_wins_over_the_category_fallback() -> None:
    """`SWAP` 类别里既有加密永续也有代币化股票永续：时段按资产判，不按类别判。"""

    moment = _et(TRADING_DAY, 17, 0)

    assert asset_session(CRYPTO, moment, inst_type="SWAP") == SESSION_REGULAR
    assert asset_session(TOKENIZED_EQUITY, moment, inst_type="SWAP") == SESSION_POST


def test_missing_asset_type_falls_back_to_the_category_rules() -> None:
    """资产类型缺失时用类别规则的 `session_kind` 兜底，而不是报错。"""

    moment = _et(KNOWN_HOLIDAYS[0], 12, 0)

    assert asset_session("", moment, inst_type="SWAP") == SESSION_CLOSED
    assert asset_session("", _et(TRADING_DAY, 12, 0), inst_type="SPOT") == SESSION_REGULAR


def test_unknown_category_without_asset_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        asset_session("", _et(TRADING_DAY, 12, 0), inst_type="FUTURES")


@pytest.mark.parametrize(
    ("asset_type", "inst_type", "ts"),
    [
        ("etf", None, _et(TRADING_DAY, 12, 0)),
        ("", None, _et(TRADING_DAY, 12, 0)),
        (TOKENIZED_EQUITY, None, datetime(2026, 11, 25, 12, 0)),
    ],
)
def test_session_lookup_rejects_unusable_inputs(
    asset_type: str, inst_type: str | None, ts: datetime
) -> None:
    with pytest.raises(ValidationError):
        asset_session(asset_type, ts, inst_type=inst_type)


def test_trading_day_predicate_agrees_with_the_session_model() -> None:
    """交易日判定与资产时段同源：周末与休市日都不是交易日。"""

    assert is_trading_day(TRADING_DAY) is True
    assert all(is_trading_day(holiday) is False for holiday in KNOWN_HOLIDAYS)
    assert is_trading_day(date(2026, 11, 28)) is False  # 周六


# ------------------------------------------------------------- 交易所时段


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (3, 59, EXCHANGE_CLOSED),
        (9, 29, EXCHANGE_CLOSED),
        (9, 30, EXCHANGE_OPEN),
        (15, 59, EXCHANGE_OPEN),
        (16, 0, EXCHANGE_CLOSED),
    ],
)
def test_exchange_session_is_open_only_during_regular_hours(
    hour: int, minute: int, expected: str
) -> None:
    assert exchange_session(_et(TRADING_DAY, hour, minute)) == expected


def test_exchange_session_is_closed_on_holidays_and_weekends() -> None:
    assert exchange_session(_et(KNOWN_HOLIDAYS[0], 12, 0)) == EXCHANGE_CLOSED
    assert exchange_session(_et(date(2026, 11, 28), 12, 0)) == EXCHANGE_CLOSED


# ------------------------------------------------------------- 来源优先级


def test_primary_source_differs_for_the_two_assets_at_the_same_moment() -> None:
    """同一时刻：代币化股票用美股代理行情，加密永续用 OKX 永续。"""

    moment = _et(TRADING_DAY, 12, 0)

    equity_source = primary_source(
        asset_session(TOKENIZED_EQUITY, moment, inst_type="SWAP"), TOKENIZED_EQUITY, "SWAP"
    )
    crypto_source = primary_source(asset_session(CRYPTO, moment, inst_type="SWAP"), CRYPTO, "SWAP")

    assert (equity_source, crypto_source) == ("us_equity_proxy", "okx_swap")


def test_closed_equity_falls_back_to_the_okx_quote() -> None:
    """美股休市时段：代币化股票永续被判为休市，但行情仍取 OKX 永续。"""

    moment = _et(KNOWN_HOLIDAYS[0], 12, 0)

    equity_session_state = asset_session(TOKENIZED_EQUITY, moment, inst_type="SWAP")
    crypto_session_state = asset_session(CRYPTO, moment, inst_type="SWAP")

    assert equity_session_state == SESSION_CLOSED
    assert crypto_session_state == SESSION_REGULAR
    assert primary_source(equity_session_state, TOKENIZED_EQUITY, "SWAP") == "okx_swap"
    assert primary_source(crypto_session_state, CRYPTO, "SWAP") == "okx_swap"


@pytest.mark.parametrize(
    ("session_state", "asset_type", "inst_type", "expected"),
    [
        (SESSION_PRE, TOKENIZED_EQUITY, "SWAP", "us_equity_proxy"),
        (SESSION_REGULAR, TOKENIZED_EQUITY, "SPOT", "us_equity_proxy"),
        (SESSION_POST, TOKENIZED_EQUITY, "SWAP", "us_equity_proxy"),
        (SESSION_CLOSED, TOKENIZED_EQUITY, "SPOT", "okx_spot"),
        (SESSION_REGULAR, CRYPTO, "SPOT", "okx_spot"),
        (SESSION_REGULAR, CRYPTO, "SWAP", "okx_swap"),
        (SESSION_CLOSED, CRYPTO, "SWAP", "okx_swap"),
    ],
)
def test_primary_source_is_a_table_of_session_times_asset(
    session_state: str, asset_type: str, inst_type: str, expected: str
) -> None:
    assert primary_source(session_state, asset_type, inst_type) == expected


def test_primary_source_rejects_unknown_sessions() -> None:
    with pytest.raises(ValidationError):
        primary_source("open", CRYPTO, "SPOT")


# ------------------------------------------------------------- 日界定界


def test_equity_daily_open_time_is_the_regular_session_open() -> None:
    """代币化股票的日线开盘时刻是当日正常时段开盘，不是 OKX 的 16:00 UTC。"""

    open_time = daily_open_time(TOKENIZED_EQUITY, _et(TRADING_DAY, 18, 0))

    assert open_time == datetime(2026, 11, 25, 14, 30, tzinfo=UTC)  # 09:30 EST
    assert int(open_time.timestamp()) % 86400 != 57600


def test_equity_daily_open_time_skips_non_trading_days() -> None:
    """周末与节假日不产生日线：日界回到上一个交易日。"""

    expected = datetime(2026, 11, 27, 14, 30, tzinfo=UTC)  # 2026-11-27（周五）09:30 EST

    assert daily_open_time(TOKENIZED_EQUITY, _et(date(2026, 11, 28), 12, 0)) == expected
    assert daily_open_time(TOKENIZED_EQUITY, _et(date(2026, 11, 29), 12, 0)) == expected


def test_equity_daily_open_time_before_the_bell_stays_on_the_previous_session() -> None:
    open_time = daily_open_time(TOKENIZED_EQUITY, _et(TRADING_DAY, 5, 0))

    assert open_time == datetime(2026, 11, 24, 14, 30, tzinfo=UTC)  # 前一日 09:30 EST


def test_crypto_daily_open_time_keeps_the_okx_utc8_anchor() -> None:
    """24/7 资产没有自己的开盘：日界仍是 OKX 的 UTC+8 零点（16:00 UTC）。"""

    open_time = daily_open_time(CRYPTO, datetime(2026, 11, 25, 18, 0, tzinfo=UTC))

    assert open_time == datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
    assert int(open_time.timestamp()) % 86400 == 57600


# ------------------------------------------------------------- 跨源偏离


def _quote(source: str, price: str, *, product_key: str = "AAPL") -> Quote:
    return Quote(
        product_key=product_key,
        source=source,
        price=Decimal(price),
        ts=datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
    )


def test_three_percent_divergence_returns_two_decimal_deviation() -> None:
    alert = divergence(_quote("okx_swap", "100"), _quote("us_equity_proxy", "103"))

    assert isinstance(alert, DivergenceAlert)
    assert alert.product_key == "AAPL"
    assert alert.deviation_pct == Decimal("3.00")
    assert str(alert.deviation_pct) == "3.00"
    assert (alert.reference.price, alert.other.price) == (Decimal("100"), Decimal("103"))
    assert (alert.reference.source, alert.other.source) == ("okx_swap", "us_equity_proxy")


def test_divergence_is_symmetric_in_magnitude() -> None:
    alert = divergence(
        _quote("okx_swap", "103"), _quote("us_equity_proxy", "100"), threshold_pct=Decimal("2")
    )

    assert alert is not None
    assert str(alert.deviation_pct) == "2.91"


def test_below_threshold_returns_no_alert() -> None:
    assert divergence(_quote("okx_swap", "100"), _quote("us_equity_proxy", "100.5")) is None


def test_threshold_is_configurable() -> None:
    alert = divergence(
        _quote("okx_swap", "100"), _quote("us_equity_proxy", "100.5"), threshold_pct=Decimal("0.5")
    )

    assert alert is not None
    assert str(alert.deviation_pct) == "0.50"
    assert str(DEFAULT_THRESHOLD_PCT) == "3"


def test_divergence_requires_two_sources_of_one_product() -> None:
    with pytest.raises(ValidationError):
        divergence(_quote("okx_swap", "100"), _quote("okx_swap", "101"))

    with pytest.raises(ValidationError):
        divergence(_quote("okx_swap", "100"), _quote("us_equity_proxy", "101", product_key="MSFT"))


def test_divergence_rejects_non_positive_prices() -> None:
    with pytest.raises(ValidationError):
        divergence(_quote("okx_swap", "0"), _quote("us_equity_proxy", "103"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"product_key": "  "},
        {"source": ""},
        {"price": Decimal("-1")},
        {"ts": datetime(2026, 11, 25, 14, 30)},
    ],
)
def test_quote_rejects_unusable_values(overrides: dict[str, object]) -> None:
    fields: dict[str, object] = {
        "product_key": "AAPL",
        "source": "okx_swap",
        "price": Decimal("100"),
        "ts": datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
    }
    fields.update(overrides)

    with pytest.raises(ValidationError):
        Quote(**fields)


def test_negative_threshold_is_rejected() -> None:
    with pytest.raises(ValidationError):
        divergence(
            _quote("okx_swap", "100"),
            _quote("us_equity_proxy", "103"),
            threshold_pct=Decimal("-1"),
        )


# ------------------------------------------------------- 日界与来源落库（读库）


PROXY_SYMBOL = "AAPL-USDT-SWAP"


class _EquityProxyPort:
    """只服务本用例的美股代理行情端口：日线按交易时段开盘定界。

    真实的美股代理适配器还没有，但 `sync_candles` 只要求端口提供 `history_candles`；
    这里是唯一的替代品，用来让写入路径（窗口对齐 → 翻页 → 落库）真的跑起来，而不是
    在用例里手算好结果再写库。
    """

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = sorted(bars, key=lambda item: item.open_time)

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        older = [bar for bar in self._bars if after is None or bar.open_time < after]
        return older[-limit:]


def _proxy_daily(open_time: datetime) -> Bar:
    """一根美股代理源日线；开盘时刻由调用方按美东 09:30 明确写出，不在此处推算。"""

    price = Decimal("100")
    return Bar(
        inst_id=PROXY_SYMBOL,
        timeframe=Timeframe.parse("1d"),
        open_time=open_time,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("10"),
        confirm=True,
        source="us_equity_proxy",
        market_session=asset_session(TOKENIZED_EQUITY, open_time, inst_type="SWAP"),
    )


def _sync_proxy_days(anchors: list[datetime]) -> None:
    """通过生产写入路径落库：窗口对齐、翻页、幂等 upsert 全走 `sync_candles`。"""

    _seed_instruments()
    sync_candles(
        _EquityProxyPort([_proxy_daily(moment) for moment in anchors]),
        PROXY_SYMBOL,
        "1d",
        anchors[0],
        anchors[-1] + timedelta(days=1),
        inst_type="SWAP",
        asset_type=TOKENIZED_EQUITY,
        source="us_equity_proxy",
    )


def test_equity_proxy_daily_bars_are_stored_on_the_session_open() -> None:
    """美股代理源的日线落在交易时段首个 open_time 上，不落在 OKX 的 16:00 UTC。

    三天的开盘时刻写死为美东 09:30（14:30 UTC）。若日界仍按 UTC+8 零点算，期望网格
    会整体错开，这三根正确的日线会被报成缺口——所以断言缺口为 0 才能区分新旧行为。
    """

    anchors = [datetime(2026, 11, day, 14, 30, tzinfo=UTC) for day in (23, 24, 25)]
    _sync_proxy_days(anchors)

    report = integrity(PROXY_SYMBOL, "1d", source="us_equity_proxy")
    with session_scope() as session:
        on_okx_boundary = session.execute(
            text(
                "SELECT COUNT(*) FROM candles WHERE bar = '1d' "
                "AND source = 'us_equity_proxy' AND open_time % 86400 = 57600"
            )
        ).scalar_one()
        stored = session.execute(
            text("SELECT open_time, market_session FROM candles WHERE source = 'us_equity_proxy'")
        ).all()

    assert on_okx_boundary == 0
    assert sorted(row[0] for row in stored) == [int(moment.timestamp()) for moment in anchors]
    assert {row[1] for row in stored} == {SESSION_REGULAR}
    assert (report.start, report.end) == (anchors[0], anchors[-1])
    assert (report.present, report.expected, report.missing, report.gaps) == (3, 3, 0, ())


def test_equity_proxy_daily_grid_skips_weekends_and_holidays() -> None:
    """美股代理源的日线只在交易日产生：跨周末与感恩节都不报缺口。"""

    anchors = [
        datetime(2026, 11, 20, 14, 30, tzinfo=UTC),  # 周五
        datetime(2026, 11, 23, 14, 30, tzinfo=UTC),  # 周一
        datetime(2026, 11, 24, 14, 30, tzinfo=UTC),  # 周二
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),  # 周三
        datetime(2026, 11, 27, 14, 30, tzinfo=UTC),  # 感恩节（26 日休市）后的周五
    ]
    _sync_proxy_days(anchors)

    report = integrity(PROXY_SYMBOL, "1d", source="us_equity_proxy")

    assert (report.present, report.expected, report.missing, report.gaps) == (5, 5, 0, ())


def test_equity_proxy_daily_gap_is_reported_when_a_trading_day_is_missing() -> None:
    """真缺一个交易日时必须报出来：网格按交易日排，不能因为不均匀就漏报。"""

    anchors = [
        datetime(2026, 11, 23, 14, 30, tzinfo=UTC),
        datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
    ]
    _sync_proxy_days(anchors)

    report = integrity(PROXY_SYMBOL, "1d", source="us_equity_proxy")

    assert report.missing == 1
    assert [(gap.start, gap.missing) for gap in report.gaps] == [
        (datetime(2026, 11, 24, 14, 30, tzinfo=UTC), 1)
    ]


def test_market_session_round_trips_through_the_table() -> None:
    open_time = datetime(2026, 11, 25, 14, 0, tzinfo=UTC)
    upsert_candles(
        [
            Bar(
                inst_id="XAAPL-USDT",
                timeframe=Timeframe.parse("1h"),
                open_time=open_time,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100.5"),
                volume=Decimal("10"),
                confirm=True,
                source="okx_spot",
                market_session=SESSION_REGULAR,
            )
        ]
    )

    bars = load_candles("XAAPL-USDT", "1h")

    assert [(bar.source, bar.market_session) for bar in bars] == [("okx_spot", SESSION_REGULAR)]


def test_bar_without_a_source_is_rejected() -> None:
    """读到空来源的 K 线必须报错，不能把「不知道从哪来的价格」当成行情用。"""

    with pytest.raises(ValidationError):
        Bar(
            inst_id="XAAPL-USDT",
            timeframe=Timeframe.parse("1h"),
            open_time=datetime(2026, 11, 25, 14, 0, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("10"),
            confirm=True,
            source="",
        )


def test_stored_row_without_a_source_fails_to_load() -> None:
    with session_scope() as session:
        session.execute(
            text(
                "INSERT INTO candles "
                "(symbol, bar, open_time, source, open, high, low, close, volume, "
                " updated_at, market_session) "
                "VALUES ('XAAPL-USDT', '1h', 1764160800, '', '100', '101', '99', '100.5', "
                "'10', 1764160800, '')"
            )
        )

    with pytest.raises(ValidationError):
        load_candles("XAAPL-USDT", "1h")


# --------------------------------------------------- 按产品取当前有效行情（读库）


def _seed_instruments() -> None:
    """产品 AAPL 与 BTC：前者只有永续，后者有永续与两个报价的现货（USDT / USDC）。"""

    sync_instruments(
        [
            make_swap_ref(inst_id="AAPL-USDT-SWAP", ct_val_ccy="AAPL"),
            make_swap_ref(inst_id="BTC-USDT-SWAP", ct_val_ccy="BTC", inst_category="1"),
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="BTC-USDC", base_ccy="BTC", quote_ccy="USDC", inst_category="1"),
        ]
    )


def _write_hourly(inst_id: str, open_time: datetime, *, source: str, close: str = "100.5") -> None:
    upsert_candles(
        [
            Bar(
                inst_id=inst_id,
                timeframe=Timeframe.parse("1h"),
                open_time=open_time,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(close),
                volume=Decimal("10"),
                confirm=True,
                source=source,
            )
        ]
    )


def test_current_bar_prefers_the_equity_proxy_during_us_regular_hours() -> None:
    _seed_instruments()
    moment = _et(TRADING_DAY, 12, 0)
    proxied = datetime(2026, 11, 25, 16, 0, tzinfo=UTC)
    _write_hourly("AAPL-USDT-SWAP", proxied, source="us_equity_proxy")
    _write_hourly("AAPL-USDT-SWAP", proxied, source="okx_swap")

    bar = current_bar("AAPL", "1h", inst_type="SWAP", at=moment)

    assert bar is not None
    assert (bar.source, bar.market_session) == ("us_equity_proxy", SESSION_REGULAR)


def test_current_bar_falls_back_to_the_okx_quote_when_the_us_market_is_closed() -> None:
    _seed_instruments()
    moment = _et(KNOWN_HOLIDAYS[0], 17, 0)
    quoted = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)
    _write_hourly("AAPL-USDT-SWAP", quoted, source="us_equity_proxy")
    _write_hourly("AAPL-USDT-SWAP", quoted, source="okx_swap")

    bar = current_bar("AAPL", "1h", inst_type="SWAP", at=moment)

    assert bar is not None
    assert bar.source == "okx_swap"
    assert bar.market_session == SESSION_CLOSED


def test_current_bar_for_a_crypto_perpetual_always_uses_the_okx_quote() -> None:
    _seed_instruments()
    _write_hourly("BTC-USDT-SWAP", datetime(2026, 11, 26, 22, 0, tzinfo=UTC), source="okx_swap")

    bar = current_bar("BTC", "1h", inst_type="SWAP", at=_et(KNOWN_HOLIDAYS[0], 17, 0))

    assert bar is not None
    assert (bar.source, bar.market_session) == ("okx_swap", SESSION_REGULAR)


def test_current_bar_of_a_crypto_spot_uses_the_quote_the_perpetual_settles_in() -> None:
    """加密现货取 `BTC-USDT`，不是字典序更靠前的 `BTC-USDC`。

    两条都写了行情：若按 `symbol` 升序取第一行，拿到的是 USDC 计价那条，价格带着计价
    单位差异，跨形态比较与偏离度都会变成假信号。
    """

    _seed_instruments()
    moment = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)
    _write_hourly("BTC-USDC", moment, source="okx_spot", close="100")
    _write_hourly("BTC-USDT", moment, source="okx_spot", close="101")

    bar = current_bar("BTC", "1h", inst_type="SPOT", at=_et(KNOWN_HOLIDAYS[0], 17, 0))

    assert bar is not None
    assert (bar.inst_id, bar.close, bar.source) == ("BTC-USDT", Decimal("101"), "okx_spot")
    assert bar.market_session == SESSION_REGULAR


def test_current_bar_returns_none_when_the_chosen_source_has_no_bars() -> None:
    _seed_instruments()

    assert current_bar("AAPL", "1h", inst_type="SWAP", at=_et(TRADING_DAY, 12, 0)) is None


def test_current_bar_rejects_an_unknown_product_or_naive_moment() -> None:
    _seed_instruments()

    with pytest.raises(ValidationError):
        current_bar("NOPE", "1h", inst_type="SWAP")
    with pytest.raises(ValidationError):
        current_bar("AAPL", "1h", inst_type="SWAP", at=datetime(2026, 11, 25, 12, 0))
    with pytest.raises(ValidationError):
        current_bar("  ", "1h", inst_type="SWAP")
    with pytest.raises(ValidationError):
        current_bar("AAPL", "1h", inst_type="  ")


def test_holiday_table_without_the_year_fails_loudly() -> None:
    """表里没有的年份直接报错：把休市日判成交易中比拒绝服务更危险。"""

    with pytest.raises(ValidationError):
        is_trading_day(date(2030, 1, 2))
