"""市场概况只有 BTC，已删除的新闻与事件接口返回 404。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import market as market_routes
from app.config import Settings
from app.core import UpstreamError
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


@pytest.mark.parametrize("path", ["/api/news", "/api/market/events"])
def test_removed_endpoints_return_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
