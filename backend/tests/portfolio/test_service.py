"""组合服务：真实落库的账本、敞口与「申请 → 批准」流程。

标的与策略实例都走业务写入路径建出来；每个用例都在独立临时 schema 里跑。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import Conflict, ValidationError
from app.db import session_scope
from app.instrument import sync_instruments
from app.portfolio import (
    TargetLegRecord,
    TargetRecord,
    create_adjustment,
    decide_adjustment,
    exposure_overview,
    get_portfolio,
    list_adjustments,
    list_portfolios,
    record_allocation,
    record_fill,
)
from tests.factories.instruments import make_ref, make_swap_ref

D = Decimal
MOMENT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.fixture()
def seeded(client: TestClient) -> TestClient:
    """两只加密现货 + 一个相对价值实例。"""

    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": "BTC/ETH 配对",
            "bar": "1d",
            "inst_ids": ["BTC-USDT", "ETH-USDT"],
        },
    )
    assert created.status_code == 201, created.text
    return client


def new_instance(client: TestClient, name: str, inst_ids: list[str]) -> str:
    created = client.post(
        "/api/strategy-instances",
        json={
            "strategy_id": "relative_value",
            "name": name,
            "bar": "1d",
            "inst_ids": inst_ids,
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["instance_id"])


def only_instance(client: TestClient) -> str:
    listed = client.get("/api/strategy-instances").json()
    return str(listed["items"][0]["instance_id"])


def test_recorded_fills_rebuild_the_fifo_ledger(seeded: TestClient) -> None:
    """三笔成交走真实落库：已实现 20，剩余成本价 110。"""

    instance = only_instance(seeded)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("100"), at=MOMENT)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("110"), at=MOMENT)
    position = record_fill(
        instance, inst_id="BTC-USDT", side="sell", qty=D("1"), price=D("120"), at=MOMENT
    )

    assert position is not None
    assert position.direction == "long"
    assert position.qty == D("1")
    assert position.avg_cost == D("110")
    assert position.mark_price == D("120")

    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.portfolio.realized_pnl == D("20")
    assert detail.portfolio.unrealized_pnl == D("10")
    assert detail.portfolio.open_positions == 1
    assert detail.portfolio.gross_exposure == D("120")
    assert detail.portfolio.net_exposure == D("120")


def test_swap_pnl_and_notional_use_contract_value(client: TestClient) -> None:
    """永续盈亏按「价差 × 张数 × 合约面值」计算，与名义价值使用同一个乘数。"""

    sync_instruments([make_swap_ref(inst_id="AAPL-USDT-SWAP", ct_val=D("10"))])
    instance = new_instance(client, "AAPL 永续", ["AAPL-USDT-SWAP"])
    record_fill(
        instance, inst_id="AAPL-USDT-SWAP", side="buy", qty=D("1"), price=D("100"), at=MOMENT
    )
    record_fill(
        instance, inst_id="AAPL-USDT-SWAP", side="buy", qty=D("1"), price=D("110"), at=MOMENT
    )
    position = record_fill(
        instance, inst_id="AAPL-USDT-SWAP", side="sell", qty=D("1"), price=D("120"), at=MOMENT
    )

    assert position is not None
    assert position.unit == "contract"
    assert position.avg_cost == D("110")
    assert position.notional == D("1200")
    assert position.unrealized_pnl == D("100")

    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.portfolio.realized_pnl == D("200")
    assert detail.portfolio.unrealized_pnl == D("100")
    assert detail.portfolio.gross_exposure == D("1200")


def test_two_instances_holding_opposite_directions_are_reported_as_conflict(
    seeded: TestClient,
) -> None:
    """两个策略对同一 product_key 持相反方向：敞口结果点名该标的与两侧策略。"""

    first = only_instance(seeded)
    second = new_instance(seeded, "反向配对", ["BTC-USDT", "ETH-USDT"])
    record_allocation(first, capital_budget=D("1000"))
    record_allocation(second, capital_budget=D("1000"))
    record_fill(first, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("100"), at=MOMENT)
    record_fill(second, inst_id="BTC-USDT", side="sell", qty=D("1"), price=D("100"), at=MOMENT)

    overview = exposure_overview()

    assert [
        (item.product_key, item.long_instance_ids, item.short_instance_ids)
        for item in overview.conflicts
    ] == [("BTC", (first,), (second,))]
    assert overview.net_exposure == D("0")
    assert overview.gross_exposure == D("0.2")
    assert overview.open_positions == 2
    assert overview.product_count == 1


def test_global_net_exposure_equals_sum_of_strategy_weights(seeded: TestClient) -> None:
    """全局净敞口 = 多头权重之和 − 空头权重之和；权重以各策略预算为分母。"""

    first = only_instance(seeded)
    second = new_instance(seeded, "做空腿", ["BTC-USDT", "ETH-USDT"])
    record_allocation(first, capital_budget=D("1000"))
    record_allocation(second, capital_budget=D("500"))
    record_fill(first, inst_id="BTC-USDT", side="buy", qty=D("6"), price=D("100"), at=MOMENT)
    record_fill(second, inst_id="ETH-USDT", side="sell", qty=D("2"), price=D("100"), at=MOMENT)

    overview = exposure_overview()

    # 600 / 1000 = 0.6 多头；200 / 500 = 0.4 空头。
    assert overview.long_exposure == D("0.6")
    assert overview.short_exposure == D("0.4")
    assert abs(overview.net_exposure - D("0.2")) < D("1e-9")
    assert overview.gross_exposure == D("1.0")
    # 单一产品净名义价值 600 ÷ 预算总和 1500。
    assert overview.largest_position_share == D("0.4")


def test_adjustment_stays_pending_until_approved(seeded: TestClient) -> None:
    """申请先落 pending，不写生效目标；批准后才生效，并留下申请人与批准人。"""

    instance = only_instance(seeded)
    target = TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id="BTC-USDT",
                inst_type="SPOT",
                direction="long",
                target_weight=D("0.25"),
            ),
        ),
        net_exposure=D("0.25"),
    )

    created = create_adjustment(
        instance_id=instance, requested_by="lxz", target=target, note="提高 BTC 权重"
    )
    assert created.status == "pending"
    assert created.decided_by is None
    assert created.decided_at is None

    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.target is None

    approved = decide_adjustment(
        created.adjustment_id, decision="approved", decided_by="reviewer", note="同意"
    )
    assert approved is not None
    assert approved.status == "approved"
    assert approved.requested_by == "lxz"
    assert approved.decided_by == "reviewer"
    assert approved.decided_at is not None
    assert approved.note == "同意"

    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.target is not None
    assert detail.target.net_exposure == D("0.25")
    assert detail.target.legs[0].inst_id == "BTC-USDT"


def test_rejected_adjustment_never_takes_effect(seeded: TestClient) -> None:
    instance = only_instance(seeded)
    target = TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id="ETH-USDT", inst_type="SPOT", direction="short", target_weight=D("0.3")
            ),
        ),
        net_exposure=D("-0.3"),
    )
    created = create_adjustment(instance_id=instance, requested_by="lxz", target=target)
    rejected = decide_adjustment(created.adjustment_id, decision="rejected", decided_by="reviewer")

    assert rejected is not None
    assert rejected.status == "rejected"
    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.target is None


def test_an_adjustment_cannot_be_decided_twice(seeded: TestClient) -> None:
    instance = only_instance(seeded)
    target = TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id="BTC-USDT", inst_type="SPOT", direction="long", target_weight=D("0.1")
            ),
        ),
        net_exposure=D("0.1"),
    )
    created = create_adjustment(instance_id=instance, requested_by="lxz", target=target)
    decide_adjustment(created.adjustment_id, decision="approved", decided_by="reviewer")

    with pytest.raises(Conflict):
        decide_adjustment(created.adjustment_id, decision="rejected", decided_by="reviewer")

    assert list_adjustments()[1] == 1


def test_concurrent_decisions_leave_one_consistent_result(seeded: TestClient) -> None:
    """两个并发决定只能有一个成功；批准失败时不会留下已生效目标。"""

    instance = only_instance(seeded)
    target = TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id="BTC-USDT", inst_type="SPOT", direction="long", target_weight=D("0.1")
            ),
        ),
        net_exposure=D("0.1"),
    )
    created = create_adjustment(instance_id=instance, requested_by="lxz", target=target)
    barrier = threading.Barrier(2, timeout=10)

    def decide(decision: str):
        barrier.wait()
        try:
            return decide_adjustment(
                created.adjustment_id,
                decision=decision,
                decided_by=f"reviewer-{decision}",
            )
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=20)
            for future in (
                pool.submit(decide, "approved"),
                pool.submit(decide, "rejected"),
            )
        ]

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    final = list_adjustments()[0][0]
    assert final.status == winners[0].status
    detail = get_portfolio(instance)
    assert detail is not None
    if final.status == "approved":
        assert detail.target == target
    else:
        assert detail.target is None


def test_target_net_exposure_must_follow_the_legs(seeded: TestClient) -> None:
    """调用方传入一个对不上的净敞口时拒绝，避免两份状态分叉。"""

    instance = only_instance(seeded)
    target = TargetRecord(
        legs=(
            TargetLegRecord(
                inst_id="BTC-USDT", inst_type="SPOT", direction="long", target_weight=D("0.2")
            ),
        ),
        net_exposure=D("0.9"),
    )

    with pytest.raises(ValidationError):
        create_adjustment(instance_id=instance, requested_by="lxz", target=target)


def test_portfolio_list_reports_budget_priority_and_zero_for_unallocated(
    seeded: TestClient,
) -> None:
    first = only_instance(seeded)
    second = new_instance(seeded, "第二", ["BTC-USDT"])
    record_allocation(first, capital_budget=D("2000"), priority=10)

    rows, total = list_portfolios()

    assert total == 2
    assert [row.instance_id for row in rows] == [first, second]
    assert rows[0].capital_budget == D("2000")
    assert rows[0].priority == 10
    assert rows[1].capital_budget == D("0")
    assert rows[1].priority == 0


def test_closed_position_keeps_realized_pnl_but_disappears_from_open_positions(
    seeded: TestClient,
) -> None:
    instance = only_instance(seeded)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("100"), at=MOMENT)
    closed = record_fill(
        instance, inst_id="BTC-USDT", side="sell", qty=D("1"), price=D("130"), at=MOMENT
    )

    assert closed is None
    detail = get_portfolio(instance)
    assert detail is not None
    assert detail.positions == ()
    assert detail.portfolio.realized_pnl == D("30")
    assert detail.portfolio.open_positions == 0


def test_unknown_instance_is_rejected_for_fills_and_allocations(client: TestClient) -> None:
    with pytest.raises(ValidationError):
        record_allocation("si_missing", capital_budget=D("1"))
    with pytest.raises(ValidationError):
        record_fill("si_missing", inst_id="BTC-USDT", side="buy", qty=D("1"), price=D("1"))


def test_position_projection_is_written_after_each_fill(seeded: TestClient) -> None:
    """投影行由成交流水重放得出：数量与成本价可以直接从库里核对。"""

    instance = only_instance(seeded)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("2"), price=D("100"), at=MOMENT)
    record_fill(instance, inst_id="BTC-USDT", side="buy", qty=D("2"), price=D("120"), at=MOMENT)

    with session_scope() as session:
        row = session.execute(
            text("SELECT qty, avg_cost FROM virtual_positions WHERE instance_id = :id"),
            {"id": instance},
        ).one()
        fills = session.execute(
            text("SELECT count(*) FROM virtual_fills WHERE instance_id = :id"),
            {"id": instance},
        ).scalar_one()

    assert row == ("4", "110")
    assert fills == 2
