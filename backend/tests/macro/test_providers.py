"""宏观数据源解析与 provider 选择。

期望值由上游真实格式反推：财政部 CSV 的列名是 `2 Yr` / `10 Yr`，日期是 `MM/DD/YYYY`；
CBOE 的列名是 `DATE` / `CLOSE`；Yahoo 是 chart JSON。`ts` 一律落到该交易日的收盘时刻，
`exchange_session(ts)` 对结算值给出 `closed`。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from app.core import UpstreamError, ValidationError
from app.macro.providers import (
    CboeProvider,
    TreasuryProvider,
    YahooProvider,
    build_provider,
    parse_cboe,
    parse_treasury,
    parse_yahoo,
    provider_names,
)
from app.market import exchange_session, settlement_epoch

TREASURY_CSV = (
    'Date,"1 Mo","2 Yr","10 Yr","30 Yr"\n'
    "11/20/2026,4.19,4.63,4.92,5.31\n"
    "11/19/2026,4.20,4.76,5.04,5.40\n"
    "11/18/2026,4.10,,5.07,5.41\n"
)

CBOE_CSV = (
    "DATE,OPEN,HIGH,LOW,CLOSE\n"
    "11/19/2026,22.06,29.13,21.84,28.44\n"
    "11/20/2026,28.63,40.03,26.94,35.89\n"
)

YAHOO_PAYLOAD = {
    "chart": {
        "result": [
            {
                "timestamp": [1795000000, 1795000060],
                "indicators": {"quote": [{"close": [4.91, None]}]},
            }
        ],
        "error": None,
    }
}


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_treasury_csv_parses_two_and_ten_year_close() -> None:
    observations = parse_treasury(TREASURY_CSV, ["us2y", "us10y"], provider="treasury")

    rows = {(item.series_id, item.ts): item for item in observations}
    latest = settlement_epoch(date(2026, 11, 20))
    assert rows[("us10y", latest)].value == Decimal("4.92")
    assert rows[("us2y", latest)].value == Decimal("4.63")
    # 11/18 的 2Y 是空单元格：那天没有发布，不能补 0 也不能算成一行。
    assert ("us2y", settlement_epoch(date(2026, 11, 18))) not in rows
    assert all(item.is_delayed is False for item in observations)
    assert exchange_session(datetime.fromtimestamp(latest, tz=UTC)) == "closed"


def test_cboe_csv_parses_vix_close() -> None:
    observations = parse_cboe(CBOE_CSV, provider="cboe")

    assert len(observations) == 2
    last = observations[-1]
    assert last.series_id == "vix"
    assert last.value == Decimal("35.89")
    assert last.is_delayed is False


def test_yahoo_payload_parses_minute_closes_as_delayed() -> None:
    observations = parse_yahoo(YAHOO_PAYLOAD, "vix", provider="yahoo")

    assert len(observations) == 1  # 第二个点是 null，跳过而不是补 0
    assert observations[0].value == Decimal("4.91")
    assert observations[0].ts == 1795000000
    assert observations[0].is_delayed is True


def test_fetch_uses_configured_url_and_filters_by_since() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=TREASURY_CSV)

    provider = TreasuryProvider(
        options={"url": "https://treasury.test/{year}"},
        client=_client(httpx.MockTransport(handler)),
    )
    since = datetime.fromtimestamp(settlement_epoch(date(2026, 11, 20)), tz=UTC)
    observations = provider.fetch(["us10y"], since)

    assert seen and seen[0].startswith("https://treasury.test/")
    assert {item.ts for item in observations} == {settlement_epoch(date(2026, 11, 20))}


def test_yahoo_uses_per_series_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [{"timestamp": [1], "indicators": {"quote": [{"close": [1.5]}]}}],
                    "error": None,
                }
            },
        )

    provider = YahooProvider(
        options={"urls": {"vix": "https://yahoo.test/vix", "us10y": "https://yahoo.test/tnx"}},
        client=_client(httpx.MockTransport(handler)),
    )
    provider.fetch(["vix"], None)

    assert seen == ["https://yahoo.test/vix"]


def test_provider_rejects_series_it_does_not_serve() -> None:
    provider = TreasuryProvider(options={"url": "https://treasury.test"}, client=None)

    with pytest.raises(UpstreamError):
        provider.fetch(["vix"], None)


def test_http_error_becomes_upstream_error() -> None:
    provider = CboeProvider(
        options={"url": "https://cboe.test/vix"},
        client=_client(httpx.MockTransport(lambda request: httpx.Response(429))),
    )

    with pytest.raises(UpstreamError, match="429"):
        provider.fetch(["vix"], None)


def test_provider_registry_exposes_three_implementations() -> None:
    assert provider_names() == ["cboe", "treasury", "yahoo"]

    with pytest.raises(ValidationError, match="未登记"):
        build_provider("alphavantage", options={})


def _yahoo_payload(close: float) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [1795000000],
                    "indicators": {"quote": [{"close": [close]}]},
                }
            ],
            "error": None,
        }
    }


def test_yahoo_float_noise_is_rounded_to_series_precision() -> None:
    """Yahoo 的分钟收盘价是二进制浮点；入库前按序列精度取整。"""

    ten_year = parse_yahoo(_yahoo_payload(4.911999702453613), "us10y", provider="yahoo")
    vix = parse_yahoo(_yahoo_payload(35.88999938964844), "vix", provider="yahoo")

    assert str(ten_year[0].value) == "4.912"  # 三位小数，没有浮点尾巴
    assert str(vix[0].value) == "35.89"  # 两位小数


def test_csv_values_keep_their_published_precision() -> None:
    observations = parse_treasury(TREASURY_CSV, ["us2y", "us10y"], provider="treasury")
    cboe = parse_cboe(CBOE_CSV, provider="cboe")

    assert observations[0].value == Decimal("4.63")
    assert cboe[-1].value == Decimal("35.89")
