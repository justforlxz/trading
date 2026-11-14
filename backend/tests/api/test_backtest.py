"""回测 API：发起、列表、排行、明细与删除，以及六条错误路径。

数据全部走业务写入路径（`sync_instruments` + `upsert_candles`），行情来源固定为
`okx_spot`：加密资产全天候交易，回测的单一数据源因此就是这只标的自己那一条序列。

断言只针对能从请求与库里复算出来的值：一笔多头交易在 `next_open` 下按下一根开盘价
成交，盈亏、逐腿贡献与排序都可以手算。
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.mapping import decimal_str
from app.api.schemas.common import DECIMAL_PATTERN
from app.backtest import BacktestTradeRow
from app.core import Bar, Timeframe
from app.db import session_scope
from app.instrument import sync_instruments
from app.market import upsert_candles
from app.strategy import StrategyLinkedBacktestRow, create_version, get_version_by_id
from tests.factories.instruments import make_ref
from tests.factories.strategies import make_strategy

DAY = timedelta(days=1)
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
CLOSES = {
    "BTC-USDT": ["100", "101", "102", "103", "104", "105"],
    "ETH-USDT": ["50", "51", "52", "53", "55", "58"],
    # 版本之外的标的：用来验证「请求的标的不在版本里」这条错误路径。
    "SOL-USDT": ["10", "11", "12", "13", "14", "15"],
}
SOURCE = "okx_spot"
PAIR_PARAMS = {"reversion_window": 3, "strength_window": 2, "pair_count": 1}
WINDOW = {"start_date": "2026-11-05", "end_date": "2026-11-10"}


def seed_market(inst_ids: Sequence[str] = INSTRUMENTS, *, source: str = SOURCE) -> None:
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
                    source=source,
                )
                for open_time, close in zip(opens, closes, strict=True)
            ]
        )


def seed_long_market(count: int = 70) -> dict[str, list[Decimal]]:
    """写入足够长的日线，让 MA20 与 MA60 都能形成完整窗口。"""

    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    opens = [AS_OF - DAY * (count - 1 - index) for index in range(count)]
    closes = {
        "BTC-USDT": [Decimal("100") + Decimal("0.5") * index for index in range(count)],
        "ETH-USDT": [Decimal("50") + Decimal("0.25") * index for index in range(count)],
    }
    for inst_id, values in closes.items():
        upsert_candles(
            [
                Bar(
                    inst_id=inst_id,
                    timeframe=Timeframe.parse("1d"),
                    open_time=open_time,
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=Decimal("10"),
                    confirm=True,
                    source=SOURCE,
                )
                for open_time, value in zip(opens, values, strict=True)
            ]
        )
    return closes


@pytest.fixture()
def version_id(client: TestClient) -> str:
    """一个相对价值版本：两只加密现货、三日回看窗口，区间与行情逐根对齐。"""

    seed_market()
    return make_strategy(
        name="BTC/ETH 相对价值",
        category="relative_value",
        direction="long_short",
        params=PAIR_PARAMS,
        inst_ids=list(INSTRUMENTS),
    ).current_version_id


def payload(version_id: str, **overrides: object) -> dict[str, object]:
    """一份可以原样重放的请求；默认只跑 BTC 一条腿。"""

    body: dict[str, object] = {
        "strategy_version_id": version_id,
        "targets": {"mode": "single", "inst_ids": ["BTC-USDT"], "group": None},
        "bar": "1d",
        **WINDOW,
        "initial_capital": "10000",
        "quote_currency": "USDT",
        "position_size": "10000",
        "max_position_pct": "1",
        "costs": {
            "maker_fee_bps": "2",
            "taker_fee_bps": "10",
            "slippage_bps": "5",
            "spread_bps": "2",
        },
        "funding_enabled": True,
        "execution_model": "next_open",
        "data_source": SOURCE,
    }
    body.update(overrides)
    return body


def run_single(client: TestClient, version_id: str, **overrides: object) -> dict[str, object]:
    created = client.post("/api/backtests", json=payload(version_id, **overrides))
    assert created.status_code == 202, created.text
    return created.json()


def test_create_backtest_returns_a_succeeded_run(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)

    assert summary["status"] == "succeeded"
    assert summary["inst_id"] == "BTC-USDT"
    assert summary["inst_type"] == "SPOT"
    assert summary["symbol_count"] == 1
    assert summary["data_source"] == SOURCE
    assert summary["is_proxy"] is False
    assert summary["strategy_version_id"] == version_id
    assert summary["params"] == PAIR_PARAMS
    assert summary["start_date"] == WINDOW["start_date"]
    assert summary["end_date"] == WINDOW["end_date"]

    metrics = summary["metrics"]
    assert metrics["initial_capital"] == "10000"
    # 结束日 23:59:59Z 收在最后一根日线（11-10 23:00Z）上，曲线覆盖全部六根。
    assert float(metrics["final_capital"]) > 0
    assert metrics["trade_count"] >= 1


def test_create_backtest_uses_next_open_and_charges_costs(
    client: TestClient, version_id: str
) -> None:
    summary = run_single(client, version_id)
    detail = client.get(f"/api/backtests/{summary['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()

    trade = body["trades"][0]
    # 建仓价 = 该根开盘价 × (1 + 滑点 + 半价差)：5 bp + 1 bp = 6 bp。开盘价取行情里
    # 的某一根，因此逐根比对，只要求命中其中一个（不假设策略在第几根建仓）。
    markup = Decimal(1) + Decimal("6") / Decimal("10000")
    candidates = {Decimal(close) * markup for close in CLOSES["BTC-USDT"]}
    assert Decimal(trade["entry_price"]) in candidates
    assert Decimal(trade["fee"]) > 0
    assert trade["funding"] is None
    assert trade["product_key"] == "BTC"
    assert trade["side"] == "long"

    # 成本确实进了净值：零成本重跑得到更高的收益。
    zero_costs = {
        "maker_fee_bps": "0",
        "taker_fee_bps": "0",
        "slippage_bps": "0",
        "spread_bps": "0",
    }
    free = run_single(client, version_id, costs=zero_costs)
    assert Decimal(free["metrics"]["total_return_pct"]) > Decimal(
        summary["metrics"]["total_return_pct"]
    )


def test_detail_exposes_portfolio_summary_and_legs(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)
    body = client.get(f"/api/backtests/{summary['run_id']}").json()

    portfolio = body["portfolio"]

    legs = body["legs"]
    assert legs, "该区间应当至少成交一条腿"
    assert [leg["product_key"] for leg in legs] == ["BTC"]
    assert {leg["side"] for leg in legs} == {"long"}
    assert legs[0]["trade_count"] == summary["metrics"]["trade_count"]
    # 贡献是该腿盈亏占初始资金的百分比；初始资金 10000，因此盈亏 = 贡献 × 100。
    leg_pnl = Decimal(legs[0]["pnl"])
    assert abs(
        Decimal(legs[0]["contribution_pct"]) - leg_pnl / Decimal("10000") * Decimal(100)
    ) < Decimal("1e-9")

    # 组合级多空合计：只有多头腿，因此空腿合计为 0。
    assert Decimal(portfolio["long_pnl"]) == leg_pnl
    assert Decimal(portfolio["short_pnl"]) == 0
    assert Decimal(portfolio["net_exposure"]) >= 0

    # 逐笔交易与曲线都在，且曲线按时间升序。
    times = [point["time"] for point in body["equity_curve"]]
    assert times == sorted(times)
    assert len(times) == 6


def test_detail_returns_the_original_request(client: TestClient, version_id: str) -> None:
    sent = payload(version_id, initial_capital="20000")
    created = client.post("/api/backtests", json=sent)
    assert created.status_code == 202, created.text

    body = client.get(f"/api/backtests/{created.json()['run_id']}").json()
    assert body["request"] == sent
    assert body["run"]["params"] == PAIR_PARAMS


def test_list_and_ranking_read_back_both_instruments(client: TestClient, version_id: str) -> None:
    payloads = [payload(version_id, targets={"mode": "list", "inst_ids": ["BTC-USDT", "ETH-USDT"]})]
    created = client.post("/api/backtests", json=payloads[0])
    assert created.status_code == 202, created.text

    listing = client.get("/api/backtests", params={"data_source": SOURCE})
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert {item["inst_id"] for item in items} == set(INSTRUMENTS)
    assert all(item["params"] == PAIR_PARAMS for item in items)
    assert listing.json()["total"] == 2

    # 其他数据源看不到这两条：不做跨源聚合。
    other = client.get("/api/backtests", params={"data_source": "okx_swap"})
    assert other.json()["total"] == 0

    ranking = client.get(
        "/api/backtests/ranking",
        params={"data_source": SOURCE, "metric": "total_return_pct"},
    )
    assert ranking.status_code == 200, ranking.text
    rows = ranking.json()["items"]
    assert len(rows) == 2
    assert all(row["params"] == PAIR_PARAMS for row in rows)
    assert len({row["run_id"] for row in rows}) == 2
    returns = [Decimal(row["total_return_pct"]) for row in rows]
    assert returns == sorted(returns, reverse=True)

    by_drawdown = client.get(
        "/api/backtests/ranking",
        params={"data_source": SOURCE, "metric": "max_drawdown_pct"},
    )
    drawdowns = [Decimal(row["max_drawdown_pct"]) for row in by_drawdown.json()["items"]]
    # 回撤是正数幅度，按它排序时最小的排在最前。
    assert drawdowns == sorted(drawdowns)


def test_list_and_ranking_distinguish_parameter_combinations(
    client: TestClient, version_id: str
) -> None:
    """换参数重跑是另一条结果：列表、排名与详情都带上该次运行实际使用的参数。"""

    baseline = run_single(client, version_id)
    changed_params = {"reversion_window": 2, "strength_window": 2, "pair_count": 1}
    version = get_version_by_id(version_id)
    assert version is not None
    changed_version = create_version(
        version.strategy_id,
        {"parameters": changed_params, "change_note": "换参数"},
    )
    assert changed_version is not None
    changed = run_single(client, changed_version.current_version_id)

    items = client.get("/api/backtests", params={"data_source": SOURCE}).json()["items"]
    listed = {item["run_id"]: item["params"] for item in items}
    assert listed[baseline["run_id"]] == PAIR_PARAMS
    assert listed[changed["run_id"]] == changed_params

    rows = client.get(
        "/api/backtests/ranking",
        params={"data_source": SOURCE, "metric": "total_return_pct"},
    ).json()["items"]
    ranked = {row["run_id"]: row["params"] for row in rows}
    assert ranked[baseline["run_id"]] == PAIR_PARAMS
    assert ranked[changed["run_id"]] == changed_params

    detail = client.get(f"/api/backtests/{changed['run_id']}").json()
    assert detail["run"]["params"] == changed_params


def test_delete_removes_the_run(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)
    deleted = client.delete(f"/api/backtests/{summary['run_id']}")
    assert deleted.status_code == 204, deleted.text

    assert client.get(f"/api/backtests/{summary['run_id']}").status_code == 404
    assert client.delete(f"/api/backtests/{summary['run_id']}").status_code == 404
    assert client.get("/api/backtests", params={"data_source": SOURCE}).json()["total"] == 0


def test_unknown_version_is_404(client: TestClient, version_id: str) -> None:
    response = client.post("/api/backtests", json=payload("sv_missing"))
    assert response.status_code == 404
    assert "sv_missing" in response.json()["detail"]


def test_category_without_template_is_400(client: TestClient, version_id: str) -> None:
    custom = make_strategy(
        name="自定义类别",
        category="custom_rules",
        params=PAIR_PARAMS,
        inst_ids=list(INSTRUMENTS),
    )
    response = client.post("/api/backtests", json=payload(custom.current_version_id))
    assert response.status_code == 400
    assert "没有对应的回测模板" in response.json()["detail"]


def test_bar_must_match_the_version(client: TestClient, version_id: str) -> None:
    response = client.post("/api/backtests", json=payload(version_id, bar="1h"))
    assert response.status_code == 400
    assert "周期" in response.json()["detail"]


def test_target_outside_the_version_is_400(client: TestClient, version_id: str) -> None:
    seed_market(("SOL-USDT",))
    response = client.post(
        "/api/backtests",
        json=payload(version_id, targets={"mode": "single", "inst_ids": ["SOL-USDT"]}),
    )
    assert response.status_code == 400
    assert "不在策略版本" in response.json()["detail"]


def test_missing_candles_are_503(client: TestClient, version_id: str) -> None:
    """该来源没有同步过行情：503「行情不可用」，不伪装成一次零交易的通过结果。"""

    response = client.post("/api/backtests", json=payload(version_id, data_source="okx_swap"))
    assert response.status_code == 503
    assert "K 线" in response.json()["detail"]


def test_sizing_cap_limits_the_weight(client: TestClient, version_id: str) -> None:
    """仓位上限压住策略权重：每笔金额 2000 / 初始资金 10000 = 0.2。"""

    capped = run_single(
        client,
        version_id,
        initial_capital="10000",
        position_size="2000",
        max_position_pct="1",
    )
    full = run_single(
        client,
        version_id,
        initial_capital="10000",
        position_size="10000",
        max_position_pct="1",
    )
    assert capped["run_id"] != full["run_id"]

    capped_detail = client.get(f"/api/backtests/{capped['run_id']}").json()
    full_detail = client.get(f"/api/backtests/{full['run_id']}").json()
    capped_qty = sum(Decimal(trade["qty"]) for trade in capped_detail["trades"])
    full_qty = sum(Decimal(trade["qty"]) for trade in full_detail["trades"])
    assert capped_qty < full_qty


def test_invalid_sizing_is_400(client: TestClient, version_id: str) -> None:
    for overrides in (
        {"max_position_pct": "0"},
        {"max_position_pct": "1.5"},
        {"position_size": "0"},
        {"initial_capital": "0"},
    ):
        response = client.post("/api/backtests", json=payload(version_id, **overrides))
        assert response.status_code == 400, (overrides, response.text)


def test_unknown_run_detail_is_404(client: TestClient) -> None:
    assert client.get("/api/backtests/bt_missing").status_code == 404


def test_batch_failure_leaves_no_partial_rows(client: TestClient) -> None:
    """批量里第二个标的没有该数据源的行情：整批失败，库里不留前一个标的的结果。

    这条用例是「一次请求先在内存里算完、再一个事务落库」的回归网：此前实现按标的逐个
    提交，BTC 已经写进库、ETH 才报错，重试会写出重复记录。
    """

    # 标的都在，但只有 BTC 有 `okx_spot` 日线：ETH 的行情放在另一个来源里。
    sync_instruments(
        [
            make_ref(inst_id="BTC-USDT", base_ccy="BTC", inst_category="1"),
            make_ref(inst_id="ETH-USDT", base_ccy="ETH", inst_category="1"),
        ]
    )
    for inst_id, source in (("BTC-USDT", SOURCE), ("ETH-USDT", "us_equity_proxy")):
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
                    source=source,
                )
                for open_time, close in zip(opens, closes, strict=True)
            ]
        )

    strategy = make_strategy(
        name="BTC/ETH 相对价值",
        category="relative_value",
        direction="long_short",
        params=PAIR_PARAMS,
        inst_ids=INSTRUMENTS,
    )

    body = payload(
        strategy.current_version_id,
        targets={"mode": "list", "inst_ids": ["BTC-USDT", "ETH-USDT"]},
    )
    response = client.post("/api/backtests", json=body)
    assert response.status_code == 400, response.text
    assert "ETH-USDT" in response.json()["detail"]

    listing = client.get("/api/backtests", params={"data_source": SOURCE}).json()
    assert listing["total"] == 0, "失败的批量请求不能在库里留下半批结果"


def test_create_writes_the_strategy_link_and_returns_run_ids(
    client: TestClient, version_id: str
) -> None:
    """批量创建返回全部运行标识与等权组合净值，并写入正式版本关联。"""

    created = client.post(
        "/api/backtests",
        json=payload(
            version_id,
            targets={"mode": "list", "inst_ids": ["BTC-USDT", "ETH-USDT"]},
        ),
    )
    assert created.status_code == 202, created.text
    body = created.json()

    assert len(body["run_ids"]) == 2
    assert body["run_id"] == body["run_ids"][0]
    assert body["combination"] == "equal_weight"
    assert "等权" in body["combination_note"]
    assert [point["time"] for point in body["group_equity"]] == sorted(
        point["time"] for point in body["group_equity"]
    )
    assert len(body["group_equity"]) == 6
    assert body["group_equity"][0]["nav"] == "1"

    with session_scope() as session:
        linked = {
            row.backtest_run_id: row.strategy_version_id
            for row in session.scalars(
                select(StrategyLinkedBacktestRow).where(
                    StrategyLinkedBacktestRow.backtest_run_id.in_(body["run_ids"])
                )
            )
        }
    assert linked == {run_id: version_id for run_id in body["run_ids"]}


def test_chart_candles_and_markers_come_from_saved_results(
    client: TestClient, version_id: str
) -> None:
    summary = run_single(client, version_id)
    detail = client.get(f"/api/backtests/{summary['run_id']}").json()
    response = client.get(f"/api/backtests/{summary['run_id']}/chart")

    assert response.status_code == 200, response.text
    chart = response.json()
    assert chart["run_id"] == summary["run_id"]
    assert chart["inst_id"] == "BTC-USDT"
    assert chart["bar"] == "1d"
    assert chart["data_source"] == SOURCE
    assert [item["time"] for item in chart["candles"]] == [
        item["time"] for item in detail["equity_curve"]
    ]
    assert all(item["is_complete"] is True for item in chart["candles"])
    assert all(item["source"] == SOURCE for item in chart["candles"])

    trades = detail["trades"]
    assert len({item["trade_id"] for item in trades}) == len(trades)
    markers = chart["markers"]
    assert len(markers) == 2 * len(trades)
    entries = [item for item in markers if item["kind"] == "entry"]
    exits = [item for item in markers if item["kind"] == "exit"]
    assert {item["trade_id"]: item["time"] for item in entries} == {
        item["trade_id"]: item["entry_time"] for item in trades
    }
    assert {item["trade_id"]: item["time"] for item in exits} == {
        item["trade_id"]: item["exit_time"] for item in trades
    }
    assert {item["trade_id"]: item["price"] for item in entries} == {
        item["trade_id"]: item["entry_price"] for item in trades
    }
    assert {item["trade_id"]: item["price"] for item in exits} == {
        item["trade_id"]: item["exit_price"] for item in trades
    }
    assert all(item["pnl"] is None and item["reason"] is None for item in entries)
    assert [item["pnl"] for item in exits] == [item["pnl"] for item in trades]
    assert [item["reason"] for item in exits] == [item["reason"] for item in trades]
    for trade in trades:
        entry_side = "buy" if trade["side"] == "long" else "sell"
        assert (
            next(item for item in entries if item["trade_id"] == trade["trade_id"])["side"]
            == entry_side
        )

    assert [item["name"] for item in chart["overlays"]] == ["MA20", "MA60"]


def test_chart_overlays_match_the_saved_candles(client: TestClient) -> None:
    closes = seed_long_market()
    strategy = make_strategy(
        name="长窗口相对价值",
        category="relative_value",
        direction="long_short",
        params=PAIR_PARAMS,
        inst_ids=list(INSTRUMENTS),
    )
    start = (AS_OF - DAY * 69).date().isoformat()
    created = client.post(
        "/api/backtests",
        json=payload(strategy.current_version_id, start_date=start),
    )
    assert created.status_code == 202, created.text

    chart = client.get(f"/api/backtests/{created.json()['run_id']}/chart").json()
    assert len(chart["candles"]) == 70
    ma20 = next(item for item in chart["overlays"] if item["name"] == "MA20")
    ma60 = next(item for item in chart["overlays"] if item["name"] == "MA60")
    assert len(ma20["points"]) == 51
    assert len(ma60["points"]) == 11
    expected = sum(closes["BTC-USDT"][-20:], Decimal(0)) / Decimal(20)
    assert ma20["points"][-1]["value"] == decimal_str(expected)


def test_equity_returns_drawdown_and_a_null_benchmark(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)
    detail = client.get(f"/api/backtests/{summary['run_id']}").json()
    response = client.get(f"/api/backtests/{summary['run_id']}/equity")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["benchmark"] is None
    assert [item["time"] for item in body["points"]] == [
        item["time"] for item in detail["equity_curve"]
    ]
    assert all(item["benchmark_equity"] is None for item in body["points"])

    peak = Decimal(detail["run"]["metrics"]["initial_capital"])
    for item in body["points"]:
        value = Decimal(item["equity"])
        peak = max(peak, value)
        expected = (value - peak) / peak
        assert abs(Decimal(item["drawdown"]) - expected) < Decimal("1e-12")


def test_replay_points_are_contiguous_and_trade_events_use_the_same_index(
    client: TestClient, version_id: str
) -> None:
    summary = run_single(client, version_id)
    detail = client.get(f"/api/backtests/{summary['run_id']}").json()
    replay = client.get(f"/api/backtests/{summary['run_id']}/replay")

    assert replay.status_code == 200, replay.text
    body = replay.json()
    points = body["points"]
    assert body["bar"] == "1d"
    assert [item["index"] for item in points] == list(range(len(points)))
    assert len(points) == len(detail["equity_curve"])
    assert [item["time"] for item in points] == [item["time"] for item in detail["equity_curve"]]
    assert all(item["close"] is not None for item in points)
    assert all({"ma20", "ma60"} <= set(item["indicators"]) for item in points)

    index_by_time = {item["time"]: item["index"] for item in points}
    events = body["trades"]
    assert len(events) == 2 * len(detail["trades"])
    for trade in detail["trades"]:
        entry = next(
            item
            for item in events
            if item["trade_id"] == trade["trade_id"] and item["kind"] == "entry"
        )
        exit_ = next(
            item
            for item in events
            if item["trade_id"] == trade["trade_id"] and item["kind"] == "exit"
        )
        assert entry["index"] == index_by_time[trade["entry_time"]]
        assert exit_["index"] == index_by_time[trade["exit_time"]]
        assert entry["price"] == trade["entry_price"]
        assert exit_["price"] == trade["exit_price"]


def test_trade_filters_and_pagination(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)
    trades = client.get(f"/api/backtests/{summary['run_id']}/trades").json()
    all_items = trades["items"]

    for side in ("long", "short"):
        filtered = client.get(
            f"/api/backtests/{summary['run_id']}/trades", params={"side": side}
        ).json()
        assert filtered["items"] == [item for item in all_items if item["side"] == side]
        assert filtered["total"] == len(filtered["items"])

    for result in ("profit", "loss"):
        filtered = client.get(
            f"/api/backtests/{summary['run_id']}/trades", params={"result": result}
        ).json()
        expected = [
            item
            for item in all_items
            if (
                Decimal(item["net_pnl"]) > 0 if result == "profit" else Decimal(item["net_pnl"]) < 0
            )
        ]
        assert filtered["items"] == expected

    filtered = client.get(
        f"/api/backtests/{summary['run_id']}/trades", params={"inst_id": "ETH-USDT"}
    ).json()
    assert filtered["items"] == []
    assert filtered["total"] == 0

    page = client.get(
        f"/api/backtests/{summary['run_id']}/trades", params={"limit": 1, "offset": 1}
    ).json()
    assert page["items"] == all_items[1:2]
    assert page["total"] == len(all_items)
    assert (page["limit"], page["offset"]) == (1, 1)


def test_trade_csv_has_bom_fixed_columns_and_escaping(client: TestClient, version_id: str) -> None:
    summary = run_single(client, version_id)
    run_id = summary["run_id"]
    detail = client.get(f"/api/backtests/{run_id}").json()
    with session_scope() as session:
        row = session.scalars(
            select(BacktestTradeRow).where(BacktestTradeRow.run_id == run_id)
        ).first()
        assert row is not None
        row.reason = "原因,含逗号"

    response = client.get(f"/api/backtests/{run_id}/trades.csv")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == [
        "标的",
        "方向",
        "开仓时间",
        "开仓价",
        "平仓时间",
        "平仓价",
        "数量",
        "手续费",
        "资金费",
        "滑点",
        "净盈亏",
        "退出原因",
    ]
    assert len(rows) - 1 == len(detail["trades"])
    trade = detail["trades"][0]
    assert rows[1] == [
        trade["inst_id"],
        "多头" if trade["side"] == "long" else "空头",
        trade["entry_time"],
        trade["entry_price"],
        trade["exit_time"],
        trade["exit_price"],
        trade["qty"],
        trade["fee"],
        "",
        trade["slippage"],
        decimal_str(Decimal(trade["pnl"]) - Decimal(trade["fee"])),
        "原因,含逗号",
    ]

    filtered = client.get(f"/api/backtests/{run_id}/trades.csv", params={"side": "short"})
    filtered_rows = list(csv.reader(io.StringIO(filtered.content.decode("utf-8-sig"))))
    assert filtered_rows[0] == rows[0]
    assert len(filtered_rows) - 1 == len(
        [item for item in detail["trades"] if item["side"] == "short"]
    )


def test_decimal_strings_fit_the_contract_precision() -> None:
    """价格连乘得到的长小数必须以契约允许的 12 位小数返回。

    真实行情价格带有两位小数，乘以数量与费率后有效数字会超过 12 位；直接把它们
    放进响应模型会触发 `DecimalString` 的格式校验，接口变成 500。
    """

    text = decimal_str(Decimal("34.83944749157491500000000001"))

    assert re.fullmatch(DECIMAL_PATTERN, text)
    assert text == "34.839447491575"
