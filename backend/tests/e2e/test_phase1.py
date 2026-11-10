"""Phase 1 端到端：标的同步 → 日线下载 → 自选读写 → 删除。

走真实的装配链路：假 OKX 服务 → `app.exchange` 适配器 → `app.market` 落库 →
HTTP 端点。断言只看可以从库里复算出来的值，不写死行情数字。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import MarketDataPort
from app.exchange import create_market_data
from app.instrument import list_instruments, sync_instruments
from app.market import load_candles, sync_candles

WATCHED = "XAAPL-USDT"
CHANGE_PLACES = Decimal("0.000001")
TURNOVER_PLACES = Decimal("0.01")


@pytest.fixture
def market_port(fake_okx_settings: Settings) -> Iterator[MarketDataPort]:
    """指向假 OKX 服务的行情实现，用例结束即关闭连接池。"""

    port = create_market_data(settings=fake_okx_settings)
    try:
        yield port
    finally:
        port.close()


def test_phase1_watchlist_round_trip(client: TestClient, market_port: MarketDataPort) -> None:
    """日常入口的核心路径：同步标的、下载日线、加自选、读行情、删自选。"""

    # 假 OKX 的现货全集里含有上游尚未开盘的 preopen 行：这类行没有 baseCcy、
    # 也没有精度，不属于可交易集合。剔除 preopen 的规则由标的解析节点（T1.8）承担，
    # 这里只同步能建行的标的，验证「同步 → 行情 → 自选」这条链路本身。
    tradable = [ref for ref in market_port.instruments("SPOT") if ref.state == "live"]
    assert sync_instruments(tradable).inserted > 0
    assert any(row.symbol == WATCHED for row in list_instruments())

    now = datetime.now(UTC).replace(microsecond=0)
    result = sync_candles(
        market_port,
        WATCHED,
        "1d",
        now - timedelta(days=4),
        now,
        inst_type="SPOT",
        asset_type="tokenized_equity",
        source="okx_spot",
    )
    assert result.inserted >= 2

    candles = load_candles(WATCHED, "1d")
    assert len(candles) >= 2
    latest, previous = candles[-1], candles[-2]

    created = client.post("/api/watchlist", json={"inst_id": WATCHED})
    assert created.status_code == 201
    item = created.json()
    assert item["instrument"]["inst_id"] == WATCHED
    assert item["instrument"]["asset_type"] == "tokenized_equity"
    assert item["group"] == "默认"

    expected_change = ((latest.close - previous.close) / previous.close * Decimal(100)).quantize(
        CHANGE_PLACES
    )
    expected_turnover = (latest.close * latest.volume).quantize(TURNOVER_PLACES)
    assert item["last_price"] == format(latest.close.normalize(), "f")
    assert item["change_pct_24h"] == format(expected_change.normalize(), "f")
    assert item["volume_24h_quote"] == format(expected_turnover.normalize(), "f")

    listing = client.get("/api/watchlist").json()
    assert [row["instrument"]["inst_id"] for row in listing["items"]] == [WATCHED]
    assert listing["groups"] == ["默认"]

    detail = client.get(f"/api/instruments/{WATCHED}")
    assert detail.status_code == 200
    assert detail.json()["instrument"]["inst_id"] == WATCHED

    series = client.get(f"/api/instruments/{WATCHED}/candles", params={"bar": "1d", "limit": 2})
    assert series.status_code == 200
    payload = series.json()
    assert payload["data_source"] == "okx_spot"
    assert payload["has_gap"] is False
    assert [row["close"] for row in payload["candles"]] == [
        format(candle.close.normalize(), "f") for candle in candles[-2:]
    ]

    removed = client.delete(f"/api/watchlist/{WATCHED}")
    assert removed.status_code == 204
    assert client.get("/api/watchlist").json()["items"] == []
