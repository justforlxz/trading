"""市场概况：BTC（OKX）+ 美股指数（读 `candles`）；已删除的接口返回 404。

两组读数各自降级：BTC 取不到不影响美股行，反之亦然。CO2 的「断网显示缓存 + stale
且不返回 500」由 `equity_overview` 的读库失败分支覆盖，这里只验证接口把它们拼在一起。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import market as market_routes
from app.config import Settings
from app.core import UpstreamError
from app.equity import EquityReading
from app.equity.service import EquityOverview
from app.exchange import OkxClient, TickerQuote
from app.market import MarketOverviewItem, market_overview_snapshot
from app.market import overview as overview_module
from app.market.overview import btc_item_from_quote

NOW = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)


class _FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def btc_item(*, as_of: datetime = NOW, value: str = "65000.5") -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol="BTC",
        name="Bitcoin",
        value=Decimal(value),
        change=Decimal("1200"),
        change_pct=Decimal("1.88"),
        market_session="regular",
        source="okx_spot",
        as_of=as_of,
        is_delayed=False,
        quality_status="normal",
        source_url=None,
    )


def empty_equity() -> EquityOverview:
    """美股区没有数据时的快照：两个标的都缺，顶层给出原因。"""

    return EquityOverview(as_of=NOW, stale=False, stale_reason=None, readings=())


@pytest.fixture(autouse=True)
def _stub_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认不读库：每个用例都从「美股区为空」出发，需要行的用例自行覆盖。"""

    monkeypatch.setattr(market_routes, "_equity_overview", empty_equity)


@pytest.fixture
def btc_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        market_routes,
        "market_overview_snapshot",
        lambda: market_overview_snapshot(
            btc_loader=btc_item,
            clock=_FixedClock(NOW),
        ),
    )


def test_overview_returns_only_btc_from_okx(client: TestClient, btc_snapshot: None) -> None:
    response = client.get("/api/market/overview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["symbol"] for item in body["items"]] == ["BTC"]
    item = body["items"][0]
    assert item["value"] == "65000.5"
    assert item["source"] == "okx_spot"
    assert item["quality_status"] == "normal"
    assert item["as_of"] is not None
    assert body["stale"] is False


def test_overview_is_stale_when_quote_is_old(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = NOW - timedelta(days=2)
    monkeypatch.setattr(
        market_routes,
        "market_overview_snapshot",
        lambda: market_overview_snapshot(
            btc_loader=lambda: btc_item(as_of=old),
            clock=_FixedClock(NOW),
        ),
    )

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert body["items"][0]["quality_status"] == "stale"
    assert "超过 24 小时" in (body["stale_reason"] or "")


def test_overview_reports_missing_when_okx_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> MarketOverviewItem:
        raise UpstreamError("上游限流")

    monkeypatch.setattr(
        market_routes,
        "market_overview_snapshot",
        lambda: market_overview_snapshot(btc_loader=broken, clock=_FixedClock(NOW)),
    )

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert body["items"][0]["value"] is None
    assert body["items"][0]["quality_status"] == "missing"
    assert "上游限流" in (body["stale_reason"] or "")


def test_btc_item_from_quote_maps_price_change_and_time() -> None:
    quote = TickerQuote(
        inst_id="BTC-USDT",
        last=Decimal("65000.5"),
        open_24h=Decimal("63800.5"),
        ts=NOW,
    )

    item = btc_item_from_quote(quote)

    assert item.symbol == "BTC"
    assert item.value == Decimal("65000.5")
    assert item.change == Decimal("1200.0")
    assert item.change_pct == Decimal("1.88")
    assert item.as_of == NOW
    assert item.source == "okx_spot"
    assert item.quality_status == "normal"


def test_btc_item_from_quote_without_open_keeps_change_pct_empty() -> None:
    quote = TickerQuote(
        inst_id="BTC-USDT",
        last=Decimal("65000.5"),
        open_24h=Decimal("0"),
        ts=NOW,
    )

    item = btc_item_from_quote(quote)

    assert item.change == Decimal("65000.5")
    assert item.change_pct is None


def test_load_okx_btc_requests_okx_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "last": "65000.5",
                        "open24h": "63800.5",
                        "ts": str(round(NOW.timestamp() * 1000)),
                    }
                ],
            },
        )

    okx_client = OkxClient(
        settings=Settings(okx_rest_base_url="https://okx.test", okx_http_max_retries=0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )
    monkeypatch.setattr(overview_module, "OkxClient", lambda: okx_client)

    item = overview_module.load_okx_btc()

    assert [request.url.path for request in requests] == ["/api/v5/market/ticker"]
    assert requests[0].url.params["instId"] == "BTC-USDT"
    assert item.value == Decimal("65000.5")
    assert item.as_of == NOW


def equity_reading(
    *,
    symbol: str = "SPY",
    value: str | None = "689.81",
    quality: str = "delayed",
    as_of: datetime | None = NOW,
) -> EquityReading:
    return EquityReading(
        symbol=symbol,
        name=f"{symbol} 名称",
        provider="yahoo",
        bar="1m",
        value=None if value is None else Decimal(value),
        as_of=as_of,
        market_session="regular",
        is_delayed=True,
        quality_status=quality,
        source_url="https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    )


def test_overview_appends_equity_rows_after_btc(
    client: TestClient, btc_snapshot: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3：首页市场概况出现 SPY / QQQ，带 `as_of`、来源与延迟标记。"""

    monkeypatch.setattr(
        market_routes,
        "_equity_overview",
        lambda: EquityOverview(
            as_of=NOW,
            stale=False,
            stale_reason=None,
            readings=(equity_reading(symbol="SPY"), equity_reading(symbol="QQQ")),
        ),
    )

    body = client.get("/api/market/overview").json()

    assert [item["symbol"] for item in body["items"]] == ["BTC", "SPY", "QQQ"]
    spy = body["items"][1]
    assert spy["value"] == "689.81"
    assert spy["source"] == "yahoo"
    assert spy["as_of"] is not None
    assert spy["is_delayed"] is True
    assert spy["quality_status"] == "delayed"
    assert spy["change"] is None
    assert body["stale"] is False


def test_overview_merges_the_equity_stale_reason(
    client: TestClient, btc_snapshot: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        market_routes,
        "_equity_overview",
        lambda: EquityOverview(
            as_of=NOW,
            stale=True,
            stale_reason="SPY 最近一根 K 线已超过 72 小时未更新",
            readings=(equity_reading(symbol="SPY", quality="stale"),),
        ),
    )

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert "72 小时" in (body["stale_reason"] or "")
    assert body["items"][1]["quality_status"] == "stale"


def test_overview_keeps_btc_when_equity_is_missing(
    client: TestClient, btc_snapshot: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """美股区缺失不影响 BTC 行：两个域的降级互不传染。"""

    monkeypatch.setattr(
        market_routes,
        "_equity_overview",
        lambda: EquityOverview(
            as_of=NOW,
            stale=True,
            stale_reason="尚未同步 SPY / QQQ 的行情",
            readings=(
                equity_reading(symbol="SPY", value=None, quality="missing", as_of=None),
                equity_reading(symbol="QQQ", value=None, quality="missing", as_of=None),
            ),
        ),
    )

    body = client.get("/api/market/overview").json()

    assert body["items"][0]["value"] == "65000.5"
    assert body["items"][0]["quality_status"] == "normal"
    assert [item["quality_status"] for item in body["items"][1:]] == ["missing", "missing"]
    assert "尚未同步" in (body["stale_reason"] or "")


@pytest.mark.parametrize("path", ["/api/news", "/api/market/events"])
def test_removed_endpoints_return_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
