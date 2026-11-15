"""五个市场指标、事件与新闻接口：来源、时间、陈旧状态与缺失字段。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.market import (
    EventInput,
    NewsInput,
    ProviderQuote,
    ProviderRateLimited,
    ProviderTimeout,
    latest_news,
    register_provider,
    upsert_market_events,
    upsert_news,
)
from app.market import external as external_module

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


class _FixedClock:
    """固定时刻的时钟：让「报价时间是否过期」的断言不随真实时间漂移。"""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class FakeProvider:
    """可控的外部 Provider：按用例返回报价或抛指定错误。"""

    name = "fake"

    def __init__(
        self,
        quotes: Sequence[ProviderQuote] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.quotes = tuple(quotes or ())
        self.error = error

    def overview(self) -> Sequence[ProviderQuote]:
        if self.error is not None:
            raise self.error
        return self.quotes

    def events(self, *, start: datetime, end: datetime) -> Sequence[EventInput]:
        return ()

    def news(self, *, tickers: Sequence[str], limit: int) -> Sequence[NewsInput]:
        return ()


def quotes() -> tuple[ProviderQuote, ...]:
    return tuple(
        ProviderQuote(
            symbol=symbol,
            value=Decimal(value),
            change=Decimal("1"),
            change_pct=Decimal("0.5"),
            as_of=NOW,
            market_session="closed",
            source_url=f"https://example.test/{symbol.lower()}",
        )
        for symbol, value in (
            ("NASDAQ", "18000"),
            ("SP500", "6000"),
            ("DOW", "42000"),
            ("VIX", "18"),
        )
    )


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider(quotes=quotes())
    register_provider("fake", lambda: provider, replace=True)
    monkeypatch.setattr(external_module, "SystemClock", lambda: _FixedClock(NOW))
    monkeypatch.setattr(
        external_module,
        "_load_okx_btc",
        lambda: ProviderQuote(
            symbol="BTC",
            value=Decimal("100000"),
            change=Decimal("1000"),
            change_pct=Decimal("1"),
            as_of=NOW,
            market_session="regular",
        ),
    )
    return provider


def _use_provider(client: TestClient, name: str = "fake") -> None:
    response = client.patch("/api/settings", json={"data_sources": {"provider": name}})
    assert response.status_code == 200, response.text


def test_overview_returns_five_items_with_source_and_time(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    _use_provider(client)

    response = client.get("/api/market/overview")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "fake"
    assert body["stale"] is False
    assert body["stale_reason"] is None
    assert [item["symbol"] for item in body["items"]] == [
        "NASDAQ",
        "SP500",
        "DOW",
        "VIX",
        "BTC",
    ]
    assert body["items"][0]["source"] == "fake"
    assert body["items"][0]["as_of"] == "2026-11-15T06:00:00Z"
    assert body["items"][0]["quality_status"] == "normal"
    assert body["items"][0]["source_url"] == "https://example.test/nasdaq"
    assert body["items"][-1]["source"] == "okx_spot"


def test_overview_marks_stale_when_quotes_are_old(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    """报价时间超过新鲜度阈值时，指标与顶层都必须显式报告过期。"""

    fake_provider.quotes = tuple(
        replace(quote, as_of=NOW - timedelta(days=3)) for quote in quotes()
    )
    _use_provider(client)

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert "过期" in body["stale_reason"]
    external = [item for item in body["items"] if item["symbol"] != "BTC"]
    assert all(item["quality_status"] == "stale" for item in external)
    assert all(item["as_of"] == "2026-11-12T06:00:00Z" for item in external)
    # BTC 由 OKX 实时行情提供，不受外部 Provider 的旧报价影响。
    assert body["items"][-1]["quality_status"] == "normal"


def test_okx_btc_change_pct_is_rounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """OKX ticker 的涨跌幅只保留两位小数，不把上游全精度写进摘要文案。"""

    class StubClient:
        def __enter__(self) -> StubClient:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def get(self, path: str, params: dict[str, str]) -> list[dict[str, str]]:
            assert path == "/api/v5/market/ticker"
            assert params == {"instId": "BTC-USDT"}
            return [{"last": "64345.9", "open24h": "67285.2", "ts": "1763186472000"}]

    monkeypatch.setattr(external_module, "OkxClient", StubClient)

    quote = external_module._load_okx_btc()

    assert quote.change_pct == Decimal("-4.37")


def test_overview_timeout_marks_stale_and_does_not_reuse_old_values(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderTimeout("上游超时")
    _use_provider(client)

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert "超时" in body["stale_reason"]
    external = [item for item in body["items"] if item["symbol"] != "BTC"]
    assert all(item["value"] is None for item in external)
    assert all(item["quality_status"] == "missing" for item in external)
    assert body["items"][-1]["symbol"] == "BTC"
    assert body["items"][-1]["value"] is not None


def test_overview_rate_limited_marks_stale(client: TestClient, fake_provider: FakeProvider) -> None:
    fake_provider.error = ProviderRateLimited("请求过多")
    _use_provider(client)

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert "限流" in body["stale_reason"]


def test_overview_missing_field_marks_stale(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    fake_provider.quotes = (ProviderQuote(symbol="NASDAQ", value=Decimal("18000"), as_of=None),)
    _use_provider(client)

    body = client.get("/api/market/overview").json()

    assert body["stale"] is True
    assert "字段" in body["stale_reason"] or "缺少" in body["stale_reason"]


def test_overview_unconfigured_provider_reports_stale(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    body = client.get("/api/market/overview").json()

    assert body["provider"] is None
    assert body["stale"] is True
    assert "未配置" in body["stale_reason"]
    assert [item["symbol"] for item in body["items"]] == [
        "NASDAQ",
        "SP500",
        "DOW",
        "VIX",
        "BTC",
    ]


def test_breadth_keeps_category_scoped_shape(client: TestClient) -> None:
    response = client.get("/api/market/breadth", params={"inst_type": "SPOT"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inst_type"] == "SPOT"
    assert set(body) == {"inst_type", "bar", "as_of", "breadth", "resonance"}
    assert client.get("/api/market/breadth").status_code == 422


def test_events_return_utc_and_beijing_display(client: TestClient) -> None:
    received = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    upsert_market_events(
        [
            EventInput(
                provider_id="evt-aapl",
                event_type="earnings",
                title="AAPL 财报",
                scheduled_at=datetime(2026, 11, 16, 21, 0, tzinfo=UTC),
                source="fake",
                received_at=received,
                region="US",
                ticker="AAPL",
                forecast="1.20",
                importance="high",
            ),
            EventInput(
                provider_id="evt-msft",
                event_type="earnings",
                title="MSFT 财报",
                scheduled_at=datetime(2026, 11, 17, 21, 0, tzinfo=UTC),
                source="fake",
                received_at=received,
                ticker="MSFT",
            ),
        ]
    )

    body = client.get("/api/market/events", params={"ticker": "AAPL"}).json()

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["ticker"] == "AAPL"
    assert item["scheduled_at"] == "2026-11-16T21:00:00Z"
    assert item["scheduled_at_beijing"] == "2026-11-17 05:00"
    assert item["source"] == "fake"


def test_news_filters_by_ticker_and_industry(client: TestClient) -> None:
    received = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    upsert_news(
        [
            NewsInput(
                provider_id="news-1",
                title="AAPL 发布业绩",
                source="fake",
                received_at=received,
                url="https://example.test/news/1",
                published_at=received,
                tickers=("AAPL",),
                tags=("technology",),
            ),
            NewsInput(
                provider_id="news-2",
                title="油价上涨",
                source="fake",
                received_at=received,
                url="https://example.test/news/2",
                published_at=received,
                tickers=("XOM",),
                tags=("energy",),
            ),
        ]
    )

    by_ticker = client.get("/api/news", params={"ticker": "AAPL"}).json()
    by_industry = client.get("/api/news", params={"industry": "energy"}).json()

    assert [item["title"] for item in by_ticker["items"]] == ["AAPL 发布业绩"]
    assert [item["title"] for item in by_industry["items"]] == ["油价上涨"]
    assert latest_news(limit=1)[0].url is not None


def test_events_reject_naive_datetime(client: TestClient) -> None:
    response = client.get("/api/market/events", params={"start": "2026-11-15T00:00:00"})

    assert response.status_code == 422


def test_news_label_filter_treats_wildcards_as_literal(client: TestClient) -> None:
    """`%` 与 `_` 是 LIKE 通配符；用户输入必须按字面量匹配。"""

    received = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    upsert_news(
        [
            NewsInput(
                provider_id="news-percent",
                title="百分比标签",
                source="fake",
                received_at=received,
                url="https://example.test/news/percent",
                published_at=received,
                tickers=("AAPL",),
                tags=("growth%",),
            ),
            NewsInput(
                provider_id="news-plain",
                title="普通标签",
                source="fake",
                received_at=received,
                url="https://example.test/news/plain",
                published_at=received,
                tickers=("AAPL",),
                tags=("growth",),
            ),
        ]
    )

    wildcard = client.get("/api/news", params={"industry": "%"}).json()
    underscore = client.get("/api/news", params={"industry": "_"}).json()
    literal = client.get("/api/news", params={"industry": "growth%"}).json()

    assert wildcard["items"] == []
    assert underscore["items"] == []
    assert [item["title"] for item in literal["items"]] == ["百分比标签"]


def test_event_lookback_uses_aware_now(client: TestClient) -> None:
    """缺省范围由服务端补全，调用方不传时间也能查询。"""

    response = client.get("/api/market/events")

    assert response.status_code == 200
    assert response.json()["items"] == []
