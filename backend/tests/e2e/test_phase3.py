"""Phase 3 端到端：模板目录 → 建实例 → 改参 → 回放 → 结果落库 → 再回放。

只走 HTTP 端点与业务写入路径（`sync_instruments` + `upsert_candles`），不直接查库里
的回放表：「结果落库」由读回 `GET /strategy-instances/{instance_id}/replays` 验证，
与界面看到的是同一条路径。行情用两个加密现货标的，回放时每个时点解析出的来源恒定。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import Bar, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from tests.factories.instruments import make_ref

DAY = timedelta(days=1)
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
CLOSES = {
    "BTC-USDT": ["100", "101", "102", "103", "104", "105"],
    "ETH-USDT": ["50", "51", "52", "53", "55", "58"],
}
WINDOW = {"start": "2026-11-05T00:00:00Z", "end": "2026-11-10T23:00:00Z"}
SCALE = Decimal("0.000000001")


def seed_market(inst_ids: Sequence[str]) -> None:
    """标的走同步路径、日线走落库路径，形状与生产写入一致。"""

    sync_instruments(
        [
            make_ref(inst_id=inst_id, base_ccy=inst_id.split("-")[0], inst_category="1")
            for inst_id in inst_ids
        ]
    )
    for inst_id in inst_ids:
        closes = CLOSES[inst_id]
        opens = [AS_OF - DAY * (len(closes) - 1 - index) for index in range(len(closes))]
        upsert_candles(
            [
                Bar(
                    inst_id=inst_id,
                    timeframe=Timeframe.parse("1d"),
                    open_time=open_time,
                    open=Decimal(close),
                    high=Decimal(close),
                    low=Decimal(close),
                    close=Decimal(close),
                    volume=Decimal("10"),
                    confirm=True,
                    source="okx_spot",
                )
                for open_time, close in zip(opens, closes, strict=True)
            ]
        )


@pytest.fixture()
def market(client: TestClient) -> TestClient:
    seed_market(["BTC-USDT", "ETH-USDT"])
    return client


def test_phase3_replay_round_trip(market: TestClient) -> None:
    """一条链路走完：目录给参数默认值 → 建实例 → 改参 → 回放 → 落库 → 再回放。"""

    catalog = market.get("/api/strategies")
    assert catalog.status_code == 200, catalog.text
    template = next(
        item for item in catalog.json()["items"] if item["strategy_id"] == "relative_value"
    )
    defaults = {param["name"]: param["default"] for param in template["params"]}
    assert defaults == {"reversion_window": 20, "strength_window": 10, "pair_count": 1}

    created = market.post(
        "/api/strategy-instances",
        json={
            "strategy_id": template["strategy_id"],
            "name": "BTC/ETH 相对价值",
            "bar": "1d",
            "params": defaults,
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    instance = created.json()
    instance_id = instance["instance_id"]
    assert instance["strategy_version"] == template["version"]
    assert instance["status"] == "strategy_generation"
    assert instance["enabled"] is True

    # 模板默认窗口要二十根日线，这里只有六根：改参是这条链路真实会出现的一步。
    patched = market.patch(
        f"/api/strategy-instances/{instance_id}",
        json={"params": {"reversion_window": 3, "strength_window": 2}, "enabled": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["params"] == {
        "reversion_window": 3,
        "strength_window": 2,
        "pair_count": 1,
    }

    path = f"/api/strategy-instances/{instance_id}/replays"
    first = market.post(path, json=WINDOW)
    assert first.status_code == 201, first.text
    replay = first.json()

    legs = replay["target"]["legs"]
    assert {leg["direction"] for leg in legs} == {"long", "short"}
    assert {leg["inst_id"] for leg in legs} == {"BTC-USDT", "ETH-USDT"}
    weights = sum(Decimal(leg["target_weight"]) for leg in legs)
    assert abs(weights - Decimal(1)) <= SCALE
    net = sum(
        Decimal(leg["target_weight"]) * (1 if leg["direction"] == "long" else -1) for leg in legs
    )
    assert Decimal(replay["target"]["net_exposure"]) == net
    assert replay["points"][-1]["as_of"] == "2026-11-10T23:00:00Z"

    # 结果落库：读回来的记录与写回的响应逐字段相同。
    stored = market.get(path)
    assert stored.status_code == 200, stored.text
    assert stored.json()["total"] == 1
    assert stored.json()["items"][0] == replay

    # 再回放：同一区间得到同一份目标组合，规范化 JSON 与哈希都不变。
    second = market.post(path, json=WINDOW)
    assert second.status_code == 201, second.text
    assert second.json()["canonical_json"] == replay["canonical_json"]
    assert second.json()["target_hash"] == replay["target_hash"]
    assert market.get(path).json()["total"] == 2

    # 停用之后不能再回放，但已经落库的记录还在。
    market.patch(f"/api/strategy-instances/{instance_id}", json={"enabled": False})
    blocked = market.post(path, json=WINDOW)
    assert blocked.status_code == 409, blocked.text
    assert market.get(path).json()["total"] == 2
