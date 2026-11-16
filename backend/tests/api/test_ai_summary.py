"""AI 摘要：来源可回溯、无来源句子不输出、过期数据显式提示。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest
from fastapi.testclient import TestClient

from app.alerts import AlertRecord
from app.api.routes import ai as ai_routes
from app.dashboard.ai_summary import DISCLAIMER, build_ai_summary
from app.market import MarketOverviewItem, MarketOverviewSnapshot

NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


def btc(*, change_pct: str = "1") -> MarketOverviewItem:
    return MarketOverviewItem(
        symbol="BTC",
        name="Bitcoin",
        value=Decimal("100000"),
        change=Decimal("1000"),
        change_pct=Decimal(change_pct),
        market_session="regular",
        source="okx_spot",
        as_of=NOW,
        is_delayed=False,
        quality_status="normal",
        source_url=None,
    )


def snapshot(*, change_pct: str = "1", stale: bool = False) -> MarketOverviewSnapshot:
    return MarketOverviewSnapshot(
        as_of=NOW,
        stale=stale,
        stale_reason="OKX BTC 报价时间已超过 24 小时" if stale else None,
        items=(btc(change_pct=change_pct),),
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
        overview=snapshot(),
        alerts=(alert("alert-1", "high"),),
    )

    assert summary.points
    assert all(point.sources for point in summary.points)
    assert all(source.id for point in summary.points for source in point.sources)
    assert summary.points[0].sources[0].type == "market_overview"
    assert summary.points[0].sources[0].id == "BTC"
    assert summary.risks[0].sources[0].type == "alert"


def test_low_severity_alert_is_not_a_risk_point() -> None:
    summary = build_ai_summary(
        generated_at=NOW,
        overview=snapshot(),
        alerts=(alert("alert-1", "warning"),),
    )

    assert summary.risks == ()


def test_stale_overview_is_explicit_in_response_and_text() -> None:
    summary = build_ai_summary(generated_at=NOW, overview=snapshot(stale=True))

    assert summary.stale is True
    assert summary.stale_notice is not None
    assert summary.overall.startswith("数据不完整")
    assert summary.disclaimer == DISCLAIMER


@pytest.mark.parametrize(
    ("change_pct", "expected"),
    [("1", "偏强"), ("-1", "偏弱"), ("0", "分化")],
)
def test_overall_follows_btc_direction(change_pct: str, expected: str) -> None:
    summary = build_ai_summary(generated_at=NOW, overview=snapshot(change_pct=change_pct))

    assert summary.overall == expected


def test_api_summary_returns_sources_and_disclaimer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_routes, "market_overview_snapshot", snapshot)

    response = client.post("/api/ai/summary")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disclaimer"] == "仅作信息归纳，不构成交易建议"
    assert body["stale"] is False
    assert body["points"]
    assert all(point["sources"] for point in body["points"])
    assert any(
        source["type"] == "market_overview" and source["id"] == "BTC"
        for point in body["points"]
        for source in point["sources"]
    )
    assert all(
        source["type"] != "news"
        for point in body["points"] + body["risks"]
        for source in point["sources"]
    )


def test_api_summary_marks_stale_when_quote_is_old(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ai_routes, "market_overview_snapshot", lambda: snapshot(stale=True))

    body = client.post("/api/ai/summary").json()

    assert body["stale"] is True
    assert body["stale_notice"] is not None
    assert "超过 24 小时" in body["stale_notice"]
    assert body["overall"].startswith("数据不完整")
