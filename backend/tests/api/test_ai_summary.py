"""AI 摘要：来源可回溯、无来源句子不输出、过期数据显式提示。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from app.alerts import AlertRecord
from app.dashboard.ai_summary import DISCLAIMER, build_ai_summary
from app.market import (
    EventInput,
    MarketOverviewItem,
    NewsInput,
    NewsItem,
    ProviderQuote,
    register_provider,
    upsert_news,
)
from app.market import (
    ExternalMarketOverview as MarketOverview,
)
from app.market import external as external_module

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


class _FixedClock:
    """固定时刻的时钟：让「报价时间是否过期」的断言不随真实时间漂移。"""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def item(symbol: str, *, value: str = "100", change_pct: str = "1") -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol=symbol,
        name=symbol,
        value=Decimal(value),
        change=Decimal("1"),
        change_pct=Decimal(change_pct),
        market_session="closed",
        source="fake",
        as_of=NOW,
        is_delayed=False,
        quality_status="normal",
        source_url=f"https://example.test/{symbol.lower()}",
    )


def overview(*items: MarketOverviewItem, stale: bool = False) -> MarketOverview:
    return MarketOverview(
        as_of=NOW,
        provider="fake",
        stale=stale,
        stale_reason="Provider 超时" if stale else None,
        last_success_at=NOW,
        items=tuple(items),
    )


def news(news_id: str, url: str | None) -> NewsItem:
    return NewsItem(
        id=news_id,
        provider_id=news_id,
        title="AAPL 发布季度业绩",
        summary=None,
        publisher=None,
        url=url,
        published_at=NOW,
        tickers=("AAPL",),
        tags=("technology",),
        source="fake",
        received_at=NOW,
    )


def alert(alert_id: str, severity: str) -> AlertRecord:
    return AlertRecord(
        id=alert_id,
        type="risk",
        severity=severity,
        instrument_id="AAPL-USDT-SWAP",
        rule_id="stop_missing",
        rule_version="b3",
        title="持仓缺少止损",
        detail="AAPL-USDT-SWAP",
        payload=MappingProxyType({}),
        status="pending",
        triggered_at=NOW,
        expires_at=None,
        updated_at=NOW,
    )


def test_every_fact_point_has_a_source() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=overview(item("NASDAQ"), item("SP500"), item("DOW")),
        news=(news("news-1", "https://example.test/news/1"),),
        alerts=(alert("alert-1", "high"),),
    )

    assert summary.points
    assert all(point.sources for point in summary.points)
    assert all(source.id for point in summary.points for source in point.sources)
    assert summary.risks[0].sources[0].type == "alert"


def test_news_without_url_is_not_output() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=overview(item("NASDAQ"), item("SP500"), item("DOW")),
        news=(news("news-1", None),),
    )

    assert all(source.type != "news" for point in summary.points for source in point.sources)


def test_low_severity_alert_is_not_a_risk_point() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=overview(item("NASDAQ"), item("SP500"), item("DOW")),
        alerts=(alert("alert-1", "warning"),),
    )

    assert summary.risks == ()


def test_stale_overview_is_explicit_in_response_and_text() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=overview(item("NASDAQ"), item("SP500"), item("DOW"), stale=True),
    )

    assert summary.stale is True
    assert summary.stale_notice == "Provider 超时"
    assert summary.overall.startswith("数据不完整")
    assert summary.disclaimer == DISCLAIMER


def test_overall_reflects_vix_and_direction() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=overview(
            item("NASDAQ", change_pct="1"),
            item("SP500", change_pct="0.5"),
            item("DOW", change_pct="0.2"),
            item("VIX", change_pct="3"),
        ),
    )

    assert summary.overall == "偏强，波动率抬升"


class FakeProvider:
    name = "fake"

    def overview(self) -> Sequence[ProviderQuote]:
        return tuple(
            ProviderQuote(
                symbol=symbol,
                value=Decimal("100"),
                change_pct=Decimal("1"),
                as_of=NOW,
            )
            for symbol in ("NASDAQ", "SP500", "DOW", "VIX")
        )

    def events(self, *, start: datetime, end: datetime) -> Sequence[EventInput]:
        return ()

    def news(self, *, tickers: Sequence[str], limit: int) -> Sequence[NewsInput]:
        return ()


class OldQuoteProvider(FakeProvider):
    """报价时间已经超过新鲜度阈值的外部 Provider。"""

    def overview(self) -> Sequence[ProviderQuote]:
        return tuple(
            ProviderQuote(
                symbol=symbol,
                value=Decimal("100"),
                change_pct=Decimal("1"),
                as_of=NOW - timedelta(days=3),
            )
            for symbol in ("NASDAQ", "SP500", "DOW", "VIX")
        )


@pytest.fixture
def summary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    register_provider("fake", FakeProvider, replace=True)
    monkeypatch.setattr(external_module, "SystemClock", lambda: _FixedClock(NOW))
    monkeypatch.setattr(
        external_module,
        "_load_okx_btc",
        lambda: ProviderQuote(
            symbol="BTC",
            value=Decimal("100000"),
            change_pct=Decimal("1"),
            as_of=NOW,
        ),
    )


def test_api_summary_returns_sources_and_disclaimer(
    client: TestClient, summary_provider: None
) -> None:
    client.patch("/api/settings", json={"data_sources": {"provider": "fake"}})
    upsert_news(
        [
            NewsInput(
                provider_id="news-api",
                title="AAPL 发布季度业绩",
                source="fake",
                received_at=NOW,
                url="https://example.test/news/api",
                published_at=NOW,
                tickers=("AAPL",),
            )
        ]
    )

    response = client.post("/api/ai/summary", json={"news_limit": 5})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disclaimer"] == "仅作信息归纳，不构成交易建议"
    assert body["stale"] is False
    assert body["points"]
    assert all(point["sources"] for point in body["points"])
    assert any(
        source["type"] == "news" and source["url"] == "https://example.test/news/api"
        for point in body["points"]
        for source in point["sources"]
    )
    assert any(
        source["type"] == "market_overview"
        for point in body["points"]
        for source in point["sources"]
    )


def test_api_summary_can_exclude_news(client: TestClient, summary_provider: None) -> None:
    client.patch("/api/settings", json={"data_sources": {"provider": "fake"}})

    body = client.post("/api/ai/summary", json={"include_news": False}).json()

    assert all(source["type"] != "news" for point in body["points"] for source in point["sources"])


def test_api_summary_rejects_unknown_field(client: TestClient) -> None:
    response = client.post("/api/ai/summary", json={"model": "gpt"})

    assert response.status_code == 422


def test_api_summary_marks_stale_when_quotes_are_old(
    client: TestClient, summary_provider: None
) -> None:
    """旧报价不能当成当前值：摘要必须带可读的过期提示与「数据不完整」结论。"""

    register_provider("old", OldQuoteProvider, replace=True)
    client.patch("/api/settings", json={"data_sources": {"provider": "old"}})

    body = client.post("/api/ai/summary", json={"include_news": False}).json()

    assert body["stale"] is True
    assert body["stale_notice"] is not None
    assert "过期" in body["stale_notice"]
    assert body["overall"].startswith("数据不完整")
