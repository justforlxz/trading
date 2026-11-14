"""Phase 3 端到端：建实例 → 改参 → 回放 → 结果落库 → 再回放。

v6 删除了策略实例的 HTTP 增删改查，回放端点也随之不再对外暴露；这条链路改为直接
走域层写入路径（`create_instance` / `prepare_replay` / `save_replay` / `list_replays`），
仍然覆盖「实例配置 → 目标组合 → 同一区间重算一致 → 执行记录落库」这一组真实行为。
行情用两个加密现货标的，回放时每个时点解析出的来源恒定。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core import Bar, Conflict, Timeframe
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.strategy import (
    create_instance,
    list_replays,
    prepare_replay,
    save_replay,
    update_instance,
)
from tests.factories.instruments import make_ref

DAY = timedelta(days=1)
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
CLOSES = {
    "BTC-USDT": ["100", "101", "102", "103", "104", "105"],
    "ETH-USDT": ["50", "51", "52", "53", "55", "58"],
}
START = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
END = AS_OF
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
def instance(client: TestClient) -> str:
    del client
    seed_market(["BTC-USDT", "ETH-USDT"])
    created = create_instance(
        strategy_id="relative_value",
        name="BTC/ETH 相对价值",
        bar="1d",
        # 模板默认窗口要二十根日线，这里只有六根：改参是这条链路真实会出现的一步。
        params={"reversion_window": 3, "strength_window": 2, "pair_count": 1},
        inst_ids=["BTC-USDT", "ETH-USDT"],
    )
    return created.instance_id


def test_phase3_replay_round_trip(instance: str) -> None:
    """一条链路走完：回放 → 落库 → 再回放，同一区间得到同一份目标组合。"""

    first = prepare_replay(instance, start=START, end=END, source="okx_spot")
    assert first is not None
    save_replay(first)

    legs = first.legs
    assert {leg.side for leg in legs} == {"long", "short"}
    assert {leg.inst_id for leg in legs} == {"BTC-USDT", "ETH-USDT"}
    weights = sum(leg.target_weight for leg in legs)
    assert abs(weights - Decimal(1)) <= SCALE
    net = sum(leg.target_weight * (1 if leg.side == "long" else -1) for leg in legs)
    assert first.net_exposure == net
    assert first.points[-1].as_of == END

    # 结果落库：读回来的记录与写回的一致。
    stored = list_replays(instance)
    assert stored is not None
    items, total = stored
    assert total == 1
    assert items[0] == first

    # 再回放：同一区间得到同一份目标组合，规范化 JSON 与哈希都不变。
    second = prepare_replay(instance, start=START, end=END, source="okx_spot")
    assert second is not None
    assert second.canonical_json == first.canonical_json
    assert second.target_hash == first.target_hash
    save_replay(second)
    assert list_replays(instance)[1] == 2  # type: ignore[index]

    # 停用之后不能再回放，但已经落库的记录还在。
    assert update_instance(instance, enabled=False) is not None
    with pytest.raises(Conflict):
        prepare_replay(instance, start=START, end=END, source="okx_spot")
    assert list_replays(instance)[1] == 2  # type: ignore[index]
