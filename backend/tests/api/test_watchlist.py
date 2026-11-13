"""自选端点：分组、条目、价格提醒、相关标的的 HTTP 契约与错误路径。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app.journal import ExecutionSnapshot, RecordedSignal
from tests.api.conftest import seed_daily, seed_instruments
from tests.factories.instruments import make_ref

DECIMAL = re.compile(r"^-?\d{1,20}(\.\d{1,12})?$")
UTC_ZULU = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_watchlist_starts_empty(market_data: TestClient) -> None:
    """没有任何条目时返回空列表与空分组，不返回 404。"""

    response = market_data.get("/api/watchlist")

    assert response.status_code == 200
    assert response.json() == {"items": [], "groups": []}


def test_add_item_returns_quote_and_registers_group(market_data: TestClient) -> None:
    """加入自选后立刻返回行情快照，并把新分组登记进列表。"""

    response = market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    assert response.status_code == 201
    body = response.json()
    assert body["group"] == "默认"
    assert body["instrument"]["inst_id"] == "XAAPL-USDT"
    assert body["instrument"]["product_key"] == "AAPL"
    assert body["instrument"]["trading_status"] == "live"
    # 最新收盘 121，前一根收盘 110；成交额 = 收盘 × 成交量 = 121 × 10。
    assert body["last_price"] == "121"
    assert body["change_pct_24h"] == "10"
    assert body["volume_24h_quote"] == "1210"
    for field in ("last_price", "change_pct_24h", "volume_24h_quote"):
        assert isinstance(body[field], str)
        assert DECIMAL.match(body[field]) is not None
    assert UTC_ZULU.match(body["instrument"]["listing_time"]) is not None
    assert body["strategy"] is None
    assert body["last_signal"] is None
    assert body["alert"] is None

    listed = market_data.get("/api/watchlist").json()
    assert listed["groups"] == ["默认"]
    assert [item["instrument"]["inst_id"] for item in listed["items"]] == ["XAAPL-USDT"]


def test_add_unknown_instrument_is_404(market_data: TestClient) -> None:
    """未同步的标的不能加入自选。"""

    response = market_data.post("/api/watchlist", json={"inst_id": "NOPE-USDT"})

    assert response.status_code == 404
    assert "NOPE-USDT" in response.json()["detail"]


def test_add_duplicate_item_is_400(market_data: TestClient) -> None:
    """同一标的重复加入属于请求冲突，返回域层的 400。"""

    assert market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"}).status_code == 201

    response = market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    assert response.status_code == 400
    assert response.json()["detail"]


def test_add_without_quotes_is_503_and_leaves_nothing(quote_less_instrument: TestClient) -> None:
    """日线不足时明确报数据不可用，且不留下半条自选。"""

    response = quote_less_instrument.post("/api/watchlist", json={"inst_id": "XETH-USDT"})

    assert response.status_code == 503
    assert response.json()["detail"]
    assert quote_less_instrument.get("/api/watchlist").json() == {"items": [], "groups": []}


def test_add_missing_inst_id_is_422(market_data: TestClient) -> None:
    """请求体缺字段由 pydantic 直接拒绝。"""

    response = market_data.post("/api/watchlist", json={})

    assert response.status_code == 422
    assert response.json()["detail"]


def test_update_group_moves_item_and_prunes_old_group(market_data: TestClient) -> None:
    """改组后旧分组不再出现在列表里，条目落在新分组。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    response = market_data.patch("/api/watchlist/XAAPL-USDT", json={"group": "科技"})

    assert response.status_code == 200
    assert response.json()["group"] == "科技"
    listed = market_data.get("/api/watchlist").json()
    assert listed["groups"] == ["科技"]
    assert listed["items"][0]["group"] == "科技"


def test_update_unknown_item_is_404(market_data: TestClient) -> None:
    """不在自选里的标的无法改组。"""

    response = market_data.patch("/api/watchlist/XAAPL-USDT", json={"group": "科技"})

    assert response.status_code == 404
    assert response.json()["detail"]


def test_delete_item_is_204_and_then_404(market_data: TestClient) -> None:
    """删除成功返回空体 204；重复删除是 404。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    first = market_data.delete("/api/watchlist/XAAPL-USDT")
    second = market_data.delete("/api/watchlist/XAAPL-USDT")

    assert first.status_code == 204
    assert first.content == b""
    assert second.status_code == 404
    assert market_data.get("/api/watchlist").json() == {"items": [], "groups": []}


def test_put_alert_creates_and_upserts(market_data: TestClient) -> None:
    """价格提醒可重复覆盖；未触发时 triggered_at 为 null。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    created = market_data.put(
        "/api/watchlist/XAAPL-USDT/alert", json={"direction": "above", "price": "130.5"}
    )
    updated = market_data.put(
        "/api/watchlist/XAAPL-USDT/alert",
        json={"direction": "below", "price": "99", "enabled": False},
    )

    assert created.status_code == 200
    assert created.json() == {
        "inst_id": "XAAPL-USDT",
        "direction": "above",
        "price": "130.5",
        "enabled": True,
        "triggered_at": None,
    }
    assert updated.status_code == 200
    assert updated.json() == {
        "inst_id": "XAAPL-USDT",
        "direction": "below",
        "price": "99",
        "enabled": False,
        "triggered_at": None,
    }
    listed = market_data.get("/api/watchlist").json()
    assert listed["items"][0]["alert"] == updated.json()


def test_delete_alert_is_204_and_then_404(market_data: TestClient) -> None:
    """删除提醒后条目的 alert 归空；重复删除是 404。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})
    market_data.put("/api/watchlist/XAAPL-USDT/alert", json={"direction": "above", "price": "130"})

    first = market_data.delete("/api/watchlist/XAAPL-USDT/alert")
    second = market_data.delete("/api/watchlist/XAAPL-USDT/alert")

    assert first.status_code == 204
    assert second.status_code == 404
    assert market_data.get("/api/watchlist").json()["items"][0]["alert"] is None


def test_put_alert_outside_watchlist_is_404(market_data: TestClient) -> None:
    """只能给自选里的标的设提醒。"""

    response = market_data.put(
        "/api/watchlist/XAAPL-USDT/alert", json={"direction": "above", "price": "130"}
    )

    assert response.status_code == 404
    assert response.json()["detail"]


def test_put_alert_rejects_unknown_direction(market_data: TestClient) -> None:
    """方向只接受 above / below。"""

    market_data.post("/api/watchlist", json={"inst_id": "XAAPL-USDT"})

    response = market_data.put(
        "/api/watchlist/XAAPL-USDT/alert", json={"direction": "sideways", "price": "130"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]


def test_related_instruments_rank_by_absolute_correlation(market_data: TestClient) -> None:
    """候选按 |相关系数| 降序；完全同步的永续排在反向相关的标的之前。"""

    seed_instruments(make_ref(inst_id="XMSFT-USDT", base_ccy="XMSFT"))
    seed_daily("XMSFT-USDT", ["121", "110", "100"])

    response = market_data.get("/api/watchlist/XAAPL-USDT/related")

    assert response.status_code == 200
    body = response.json()
    assert body["inst_id"] == "XAAPL-USDT"
    assert body["window_days"] == 30
    assert [item["inst_id"] for item in body["items"]] == ["AAPL-USDT-SWAP", "XMSFT-USDT"]
    # 永续收盘恒为现货的一半 → 相关系数精确为 1；反向序列只是在 |相关系数| 上接近 1。
    assert body["items"][0]["correlation"] == "1"
    assert float(body["items"][1]["correlation"]) < -0.99
    assert body["items"][0]["window_days"] == 30
    assert body["items"][0]["product_key"] == "AAPL"
    for item in body["items"]:
        assert DECIMAL.match(item["correlation"]) is not None


def test_related_unknown_instrument_is_404(market_data: TestClient) -> None:
    """未知标的无法算相关标的。"""

    response = market_data.get("/api/watchlist/NOPE-USDT/related")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_related_window_days_out_of_range_is_422(market_data: TestClient) -> None:
    """窗口天数必须落在 5–180。"""

    response = market_data.get("/api/watchlist/XAAPL-USDT/related", params={"window_days": 4})

    assert response.status_code == 422
    assert response.json()["detail"]


def test_watchlist_accepts_commodity_token(client: TestClient) -> None:
    """商品代币既能加自选，也能整表读回；契约取值不比领域层窄。"""

    seed_instruments(make_ref(inst_id="XAUT-USDT", base_ccy="XAUT", inst_category="4"))
    seed_daily("XAUT-USDT", ["10", "11"])

    created = client.post("/api/watchlist", json={"inst_id": "XAUT-USDT"})

    assert created.status_code == 201
    assert created.json()["instrument"]["asset_type"] == "commodity_token"

    listed = client.get("/api/watchlist")
    assert listed.status_code == 200
    assert [item["instrument"]["inst_id"] for item in listed.json()["items"]] == ["XAUT-USDT"]


def test_patch_group_requires_group_field(market_data: TestClient) -> None:
    """缺少 group 字段按请求校验拒绝，而不是默认移回默认分组。"""

    response = market_data.patch("/api/watchlist/XAAPL-USDT", json={})

    assert response.status_code == 422
    assert response.json()["detail"]


def test_watchlist_rows_compose_running_strategy_and_latest_signal(client: TestClient) -> None:
    """列表行带运行策略与最近信号；没有关联的标的如实返回空值。"""

    seed_instruments(make_ref(), make_ref(inst_id="XETH-USDT", base_ccy="XETH"))
    seed_daily("XAAPL-USDT", ["100", "110", "121"])
    seed_daily("XETH-USDT", ["50", "51", "52"])
    for inst_id in ("XAAPL-USDT", "XETH-USDT"):
        assert client.post("/api/watchlist", json={"inst_id": inst_id}).status_code == 201

    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "directional",
            "name": "AAPL 方向",
            "bar": "1d",
            "params": {"trend_window": 2, "momentum_window": 1, "leg_count": 2},
            "inst_ids": ["XAAPL-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    instance_id = created.json()["instance_id"]

    client.app.state.execution_snapshot = ExecutionSnapshot(
        signals=(
            RecordedSignal(
                signal_id="sig-1",
                instance_id=instance_id,
                inst_id="XAAPL-USDT",
                inst_type="SPOT",
                side="long",
                strength=0.8,
                price=Decimal("121"),
                reason="趋势向上",
                generated_at=datetime(2026, 11, 10, 7, tzinfo=UTC),
            ),
        )
    )
    try:
        response = client.get("/api/watchlist")
    finally:
        client.app.state.execution_snapshot = ExecutionSnapshot()

    assert response.status_code == 200, response.text
    items = {item["instrument"]["inst_id"]: item for item in response.json()["items"]}

    aapl = items["XAAPL-USDT"]
    assert aapl["strategy"] == {
        "instance_id": instance_id,
        "name": "AAPL 方向",
        "status": "strategy_generation",
        "execution_mode": "manual",
        "enabled": True,
    }
    assert aapl["last_signal"] == {
        "signal_id": "sig-1",
        "strategy_instance_id": instance_id,
        "inst_id": "XAAPL-USDT",
        "inst_type": "SPOT",
        "action": "BUY",
        "bar": "1d",
        "price": "121",
        "reason": "趋势向上",
        "generated_at": "2026-11-10T07:00:00Z",
        "target_weight": None,
    }

    assert items["XETH-USDT"]["strategy"] is None
    assert items["XETH-USDT"]["last_signal"] is None
