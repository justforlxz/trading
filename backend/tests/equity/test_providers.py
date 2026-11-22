"""美股 provider 的对外承诺：可切换、周期由实现声明、时刻按美股规则定界。

`build_provider` 把上游取数实现（`app.exchange`）包成 `BarProvider`：补周期、写来源名、
把上游时刻对齐到 `candles` 的规范 `open_time`。这一层不认识 HTTP 细节，只验证映射。
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.core import ValidationError
from app.equity.providers import (
    build_provider,
    provider_bar,
    provider_delayed,
    provider_names,
    provider_template,
    provider_url,
)
from app.market import US_EQUITY, daily_open_time, floor_open_time

STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-11-20,687.5,690,687,689.81,151413318\n"
    "2026-11-19,680,688,679,686.2,140000000\n"
)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 11, 21, tzinfo=UTC)


def _stooq_provider() -> object:
    return build_provider(
        "stooq",
        options={"url": "https://stooq.test/q/d/l/?s={symbol}.us&i=d"},
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=STOOQ_CSV))
        ),
    )


def test_provider_names_come_from_the_registry() -> None:
    assert provider_names() == ["stooq", "yahoo"]


def test_bar_is_declared_by_the_implementation() -> None:
    """周期由实现声明：Yahoo 只给分钟级、Stooq 只给日线，切换即换周期。"""

    assert provider_bar("yahoo") == "1m"
    assert provider_bar("stooq") == "1d"


def test_both_free_providers_are_delayed() -> None:
    """免费源都是延迟行情，`is_delayed` 不得写成实时。"""

    assert provider_delayed("yahoo") is True
    assert provider_delayed("stooq") is True


def test_unknown_provider_name_is_a_validation_error() -> None:
    with pytest.raises(ValidationError, match="polygon"):
        build_provider("polygon", options={})


def test_yahoo_bars_keep_the_minute_open_time_and_carry_the_source() -> None:
    end = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
    stamp = int(end.timestamp()) - 60
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [stamp],
                    "indicators": {
                        "quote": [
                            {
                                "open": [688.0],
                                "high": [690.0],
                                "low": [687.5],
                                "close": [689.81],
                                "volume": [12],
                            }
                        ]
                    },
                }
            ]
        }
    }
    provider = build_provider(
        "yahoo",
        options={"url": "https://yahoo.test/chart/{symbol}"},
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )

    bars = provider.fetch(["SPY"], START, end)

    assert len(bars) == 1
    bar = bars[0]
    assert bar.source == "yahoo"
    assert bar.timeframe.value == "1m"
    assert bar.confirm is True
    assert bar.open_time == floor_open_time(datetime.fromtimestamp(stamp, tz=UTC), "1m", US_EQUITY)


def test_stooq_daily_bars_align_to_the_us_session_open() -> None:
    """日线的 `open_time` 是该交易日正常时段开盘（美东 09:30），不是 UTC 午夜。"""

    provider = _stooq_provider()

    bars = provider.fetch(["SPY"], START, END)

    assert [bar.open_time for bar in bars] == [
        daily_open_time(US_EQUITY, datetime(2026, 11, 20, 16, 0, tzinfo=UTC)),
        daily_open_time(US_EQUITY, datetime(2026, 11, 19, 16, 0, tzinfo=UTC)),
    ]
    assert bars[0].timeframe.value == "1d"
    assert bars[0].source == "stooq"


def test_provider_url_substitutes_the_symbol_for_a_usable_link() -> None:
    """来源链接必须是能点开的真实地址，不能把 `{symbol}` 原样留给首页。"""

    assert "{symbol}" in (provider_template("yahoo") or "")
    yahoo = provider_url("yahoo", "SPY")
    assert yahoo is not None and "{symbol}" not in yahoo and "SPY" in yahoo
    # Stooq 的代码是「小写 + 市场后缀」：显示链接与抓取时请求的地址逐字一致。
    stooq = provider_url("stooq", "QQQ")
    assert stooq == "https://stooq.com/q/d/l/?s=qqq.us&i=d"
    assert provider_url("polygon", "SPY") is None
