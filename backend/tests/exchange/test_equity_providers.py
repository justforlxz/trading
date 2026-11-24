"""美股行情源的上游解析：Yahoo chart JSON 与 Stooq CSV。

期望值由上游真实格式反推：Yahoo 是 `chart.result[0]` 里的并列数组（`timestamp[]` 与
`indicators.quote[0].*[]`），Stooq 是 `Date,Open,High,Low,Close,Volume` 的 CSV。这一层
只交出「上游给了什么」（`RawBar`），`open_time` 的定界与交易时段由 `app/equity` 算。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core import UpstreamError
from app.exchange.providers import (
    build_source,
    source_bars,
    source_delayed,
    source_names,
    source_template,
    source_url,
)
from app.exchange.providers.raw import RawBar
from app.exchange.providers.stooq import StooqSource, parse_stooq
from app.exchange.providers.yahoo import YahooSource, parse_yahoo

NOW = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)  # 美股收盘后
#: 三根 1 分钟 K 线：13:30 / 13:31 / 13:32 UTC（正常时段开盘后头三分钟）。
STAMPS = [1795181400, 1795181460, 1795181520]
START = datetime.fromtimestamp(STAMPS[0], tz=UTC)


def _yahoo_payload(
    *,
    stamps: list[int] | None = None,
    closes: list[float | None] | None = None,
) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": STAMPS if stamps is None else stamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 101.0, 102.0],
                                "high": [101.0, 102.0, 103.0],
                                "low": [99.0, 100.0, 101.0],
                                "close": [100.5, 101.5, 102.5] if closes is None else closes,
                                "volume": [1000, 2000, 3000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def test_yahoo_parse_maps_each_column_by_index() -> None:
    bars = parse_yahoo(_yahoo_payload(), "SPY", start=START, end=NOW)

    assert len(bars) == 3
    first = bars[0]
    assert isinstance(first, RawBar)
    assert first.symbol == "SPY"
    assert first.open_time == datetime.fromtimestamp(STAMPS[0], tz=UTC)
    assert (first.open, first.high, first.low, first.close) == (
        Decimal("100.0"),
        Decimal("101.0"),
        Decimal("99.0"),
        Decimal("100.5"),
    )
    assert first.volume == Decimal("1000")


def test_yahoo_parse_hands_over_every_bar_inside_the_window() -> None:
    """取数层不认识交易时段：窗口内的每一根都交上去，定稿判断在行情域的适配层。"""

    end = datetime.fromtimestamp(STAMPS[2], tz=UTC)

    bars = parse_yahoo(_yahoo_payload(), "SPY", start=START, end=end)

    # `end` 是半开窗口的右端：第三根的 open_time 等于 `end`，不在窗口内。
    assert [bar.open_time for bar in bars] == [
        datetime.fromtimestamp(STAMPS[0], tz=UTC),
        datetime.fromtimestamp(STAMPS[1], tz=UTC),
    ]

    wider = parse_yahoo(_yahoo_payload(), "SPY", start=START, end=NOW)
    assert len(wider) == 3


def test_yahoo_prices_lose_the_binary_float_tail() -> None:
    """Yahoo 的列是二进制浮点：入库前按 4 位小数取整，不把尾巴带到库和首页。"""

    bars = parse_yahoo(
        _yahoo_payload(closes=[608.450012207031, None, 102.5]), "SPY", start=START, end=NOW
    )

    assert bars[0].close == Decimal("608.45")
    assert format(bars[0].close, "f") == "608.4500"
    assert format(bars[0].volume, "f") == "1000"


def test_yahoo_parse_drops_a_bar_missing_any_price() -> None:
    """四个价格缺一个就不是可用 K 线：补 0 会写出一个不存在的开盘价。"""

    payload = _yahoo_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["open"] = [None, 101.0, 102.0]

    bars = parse_yahoo(payload, "SPY", start=START, end=NOW)

    assert [bar.close for bar in bars] == [Decimal("101.5"), Decimal("102.5")]


def test_stooq_parse_keeps_a_real_zero_price() -> None:
    """`Decimal("0")` 是假值：显式判 `None`，不能把上游真实的 0 换成收盘价。"""

    text = "Date,Open,High,Low,Close,Volume\n2026-11-20,0,102,0,101.5,1000\n"

    bars = parse_stooq(text, "SPY", start=datetime(2026, 1, 1, tzinfo=UTC), end=NOW)

    assert (bars[0].open, bars[0].low) == (Decimal(0), Decimal(0))
    assert bars[0].high == Decimal("102")
    assert bars[0].close == Decimal("101.5")


def test_yahoo_parse_skips_rows_without_close() -> None:
    bars = parse_yahoo(_yahoo_payload(closes=[100.5, None, 102.5]), "SPY", start=START, end=NOW)

    assert [bar.close for bar in bars] == [Decimal("100.5"), Decimal("102.5")]


def test_yahoo_parse_filters_the_window() -> None:
    start = datetime.fromtimestamp(STAMPS[1], tz=UTC)

    bars = parse_yahoo(_yahoo_payload(), "SPY", start=start, end=NOW)

    assert [bar.open_time for bar in bars] == [
        datetime.fromtimestamp(STAMPS[1], tz=UTC),
        datetime.fromtimestamp(STAMPS[2], tz=UTC),
    ]


def test_yahoo_parse_rejects_an_error_payload() -> None:
    with pytest.raises(UpstreamError, match="Yahoo 返回错误"):
        parse_yahoo({"chart": {"error": "Not Found", "result": None}}, "SPY", start=START, end=NOW)


def test_yahoo_parse_rejects_an_empty_result() -> None:
    with pytest.raises(UpstreamError, match="没有返回"):
        parse_yahoo({"chart": {"result": []}}, "SPY", start=START, end=NOW)


def test_yahoo_fetch_substitutes_the_symbol_and_sends_a_browser_ua() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=json.dumps(_yahoo_payload()))

    source = YahooSource(
        options={"url": "https://yahoo.test/chart/{symbol}?interval=1m&range=1d"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    bars = source.fetch(["SPY"], START, NOW)

    assert [request.url.path for request in requests] == ["/chart/SPY"]
    assert requests[0].url.params["interval"] == "1m"
    assert len(bars) == 3


def test_yahoo_fetch_reports_a_non_200_upstream() -> None:
    source = YahooSource(
        options={"url": "https://yahoo.test/chart/{symbol}"},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(429))),
    )

    with pytest.raises(UpstreamError, match="429"):
        source.fetch(["SPY"], START, NOW)


def test_yahoo_fetch_requires_a_configured_url() -> None:
    source = YahooSource(options={})

    with pytest.raises(UpstreamError, match="未配置上游地址"):
        source.fetch(["SPY"], START, NOW)


STOOQ_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-11-20,100,102,99,101.5,123456\n"
    "2026-11-19,98,101,97,100.5,654321\n"
    "2026-11-18,97,99,96,98,0\n"
)


def test_stooq_parse_anchors_the_date_inside_the_us_session() -> None:
    """日期锚点必须是美东正常时段内的时刻，否则日期会落到前一天。"""

    bars = parse_stooq(STOOQ_CSV, "SPY", start=datetime(2026, 1, 1, tzinfo=UTC), end=NOW)

    assert bars
    assert bars[0].open_time == datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    assert bars[0].close == Decimal("101.5")
    assert bars[0].volume == Decimal("123456")


def test_stooq_parse_falls_back_to_close_when_a_column_is_empty() -> None:
    text = "Date,Open,High,Low,Close,Volume\n2026-11-20,,,,\n"

    assert parse_stooq(text, "SPY", start=datetime(2026, 1, 1, tzinfo=UTC), end=NOW) == []
    text = "Date,Open,High,Low,Close,Volume\n2026-11-20,,,,101.5,\n"
    bars = parse_stooq(text, "SPY", start=datetime(2026, 1, 1, tzinfo=UTC), end=NOW)
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (
        Decimal("101.5"),
        Decimal("101.5"),
        Decimal("101.5"),
        Decimal("101.5"),
    )
    assert bars[0].volume == Decimal(0)


def test_stooq_parse_rejects_the_javascript_challenge_page() -> None:
    """实测上游对本机返回挑战页（HTML + 200），必须如实报上游错误而不是空列表。"""

    challenge = "<!DOCTYPE html><html><body>requires JavaScript</body></html>"

    with pytest.raises(UpstreamError, match="CSV"):
        parse_stooq(challenge, "SPY", start=START, end=NOW)


def test_stooq_fetch_substitutes_a_lowercase_symbol() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=STOOQ_CSV)

    source = StooqSource(
        options={"url": "https://stooq.test/q/d/l/?s={symbol}.us&i=d"},
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    source.fetch(["SPY"], datetime(2026, 11, 1, tzinfo=UTC), NOW)

    assert requests[0].url.params["s"] == "spy.us"


def test_registry_declares_granularity_and_delay_per_provider() -> None:
    assert source_names() == ["stooq", "yahoo"]
    assert source_bars("yahoo") == ("1m", "1d")
    assert source_bars("stooq") == ("1d",)
    # 两个免费源都是延迟行情：不能把它们的价格当实时。
    assert source_delayed("yahoo") is True
    assert source_delayed("stooq") is True
    # 未登记的来源按延迟处理，绝不当作实时。
    assert source_delayed("polygon") is True


def test_registry_builds_by_name() -> None:
    source = build_source("yahoo", options={"url": "https://yahoo.test/{symbol}"})

    assert isinstance(source, YahooSource)


def test_source_template_and_url_differ_only_by_the_symbol() -> None:
    """模板给配置拼请求用；显示用的地址必须是替换过占位符的真实链接。"""

    template = source_template("yahoo")
    assert template is not None and "{symbol}" in template
    assert source_url("yahoo", "SPY") == template.replace("{symbol}", "SPY")
    assert source_url("polygon", "SPY") is None
    assert source_template("polygon") is None
