"""Phase 4 端到端：选策略版本 → 选标的集合 → 设成本 → 跑批量 → 看排名 → 打开单条。

只走 HTTP 端点与业务写入路径（假 OKX 服务 → 交易适配器 → `sync_instruments` +
`sync_candles`），不直接查回测表：「结果落库」由读回 `GET /backtests` 与
`GET /backtests/{run_id}` 验证，与界面看到的是同一条路径。行情用两只加密现货的日线，
来源固定 `okx_spot`，全程不联网。

验收覆盖：
- 一次批量请求为每个标的各落一条运行，列表与排行榜都能读回；
- 排行榜按指标排序，且回撤按「正数幅度、最小在前」；
- 单条结果的组合级汇总在上、逐腿明细在下，多腿与空腿合计分别等于逐腿盈亏之和；
- 逐笔交易、资金曲线都在，曲线时段与行情逐根对齐；
- 换一组参数重跑得到另一组结果，两条都能在列表里对比；
- 同参数重跑得到逐字段相同的结果；删除后不再出现在列表里。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from math import sin

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import MarketDataPort
from app.exchange import create_market_data
from app.instrument import sync_instruments
from app.market import CRYPTO, sync_candles
from app.strategy import create_version, get_version_by_id
from tests.factories.strategies import make_strategy
from tests.fakes.okx.server import start_server
from tests.fakes.okx.store import OkxStore

DAY = timedelta(days=1)
LOOKBACK_DAYS = 40
SERIES_BARS = 36
#: 最后四根日线的收盘价完全相同：均值回归与相对强弱同时归零，策略在倒数第二根
#: 给出空目标，最后一根才会执行平仓，端到端因此一定能读到已完成的逐笔交易。
FLAT_TAIL_BARS = 4
INST_IDS = ("BTC-USDT", "ETH-USDT")
SOURCE = "okx_spot"
NOW = datetime.now(UTC).replace(microsecond=0)
START = (NOW - LOOKBACK_DAYS * DAY).date().isoformat()
END = NOW.date().isoformat()
LAST_DAILY_OPEN = datetime.combine(NOW.date(), time(16, 0), tzinfo=UTC)
if LAST_DAILY_OPEN >= NOW:
    LAST_DAILY_OPEN -= DAY
PARAMS = {"reversion_window": 3, "strength_window": 2, "pair_count": 1}
COSTS = {
    "maker_fee_bps": "2",
    "taker_fee_bps": "10",
    "slippage_bps": "5",
    "spread_bps": "2",
}
TOL = Decimal("1e-9")
MILLIONTH = Decimal("0.000001")


def _correlated_daily_series() -> dict[str, dict[str, list[list[str]]]]:
    """BTC 与 ETH 的高相关日线：共同波动决定方向，小幅反向摆动制造相对偏离。

    假 OKX 默认按标的名各自生成价格，两条序列互不相关，相对价值策略永远配不出对。
    这里给两只标的同一条主趋势加一个方向相反的小摆动：相关系数足够高（能配对），
    均值回归与相对强弱的分数又不同（有偏离可分）。最后四根压成同一收盘价，让组合
    在区间末尾清仓，逐笔交易因此不会全是未平仓。
    """

    rows: dict[str, list[list[str]]] = {inst_id: [] for inst_id in INST_IDS}
    previous = {inst_id: Decimal("100.00") for inst_id in INST_IDS}
    for index in range(SERIES_BARS):
        moment = LAST_DAILY_OPEN - DAY * (SERIES_BARS - 1 - index)
        if index >= SERIES_BARS - FLAT_TAIL_BARS:
            closes = {inst_id: Decimal("100.00") for inst_id in INST_IDS}
        else:
            base = 100.0 + 8.0 * sin(index / 4)
            wobble = 1.5 * sin(index / 2)
            closes = {
                "BTC-USDT": Decimal(f"{base + wobble:.2f}"),
                "ETH-USDT": Decimal(f"{base - wobble:.2f}"),
            }
        for inst_id, close in closes.items():
            open_price = previous[inst_id]
            high = max(open_price, close) + Decimal("0.50")
            low = min(open_price, close) - Decimal("0.50")
            volume = Decimal("1000.00")
            turnover = volume * close
            rows[inst_id].append(
                [
                    str(int(moment.timestamp()) * 1000),
                    f"{open_price:.2f}",
                    f"{high:.2f}",
                    f"{low:.2f}",
                    f"{close:.2f}",
                    f"{volume:.2f}",
                    f"{turnover:.2f}",
                    f"{turnover:.2f}",
                    "1",
                ]
            )
            previous[inst_id] = close
    return {inst_id: {"1D": series} for inst_id, series in rows.items()}


@pytest.fixture()
def fake_okx_settings() -> Iterator[Settings]:
    """指向带固定相关行情的假 OKX；只为本模块覆盖默认的数据源。"""

    with start_server(port=0, store=OkxStore(candle_series=_correlated_daily_series())) as server:
        yield Settings(
            okx_rest_base_url=server.base_url,
            okx_http_max_retries=0,
            okx_rate_limit_capacity=1000,
            okx_rate_limit_refill_per_second=1000.0,
        )


@dataclass(frozen=True, slots=True)
class SeededMarket:
    """一个已经建好的策略版本，以及行情里实际可用的日线根数。"""

    version_id: str
    bar_count: int


def seed_market(port: MarketDataPort) -> int:
    """标的与日线都从假 OKX 服务同步落库，形状与生产写入一致。

    日线窗口取「当下往前若干天」：假 OKX 只生成最近的历史，固定日期会随运行时间
    失效。返回该窗口里 BTC 实际写入的根数，供资金曲线逐 bar 断言使用。
    """

    tradable = [ref for ref in port.instruments("SPOT") if ref.inst_id in INST_IDS]
    assert {ref.inst_id for ref in tradable} == set(INST_IDS)
    sync_instruments(tradable)

    start = datetime.combine(datetime.fromisoformat(START).date(), time.min, tzinfo=UTC)
    bar_count = 0
    for inst_id in INST_IDS:
        result = sync_candles(
            port,
            inst_id,
            "1d",
            start,
            NOW,
            inst_type="SPOT",
            asset_type=CRYPTO,
            source=SOURCE,
        )
        assert result.inserted >= 4, f"{inst_id} 的日线不足以产生回测信号"
        if inst_id == INST_IDS[0]:
            bar_count = result.inserted
    return bar_count


@pytest.fixture()
def seeded(client: TestClient, fake_okx_settings: Settings) -> Iterator[SeededMarket]:
    """一个相对价值版本：BTC 与 ETH 两条腿，行情与区间逐根对齐。"""

    port = create_market_data(settings=fake_okx_settings)
    try:
        bar_count = seed_market(port)
        strategy = make_strategy(
            name="BTC/ETH 相对价值",
            category="relative_value",
            direction="long_short",
            params=PARAMS,
            inst_ids=INST_IDS,
        )
        yield SeededMarket(strategy.current_version_id, bar_count)
    finally:
        port.close()


@pytest.fixture()
def version_id(seeded: SeededMarket) -> str:
    return seeded.version_id


def request_body(
    version_id: str,
    *,
    inst_ids: Sequence[str] = INST_IDS,
    costs: dict[str, str] | None = None,
) -> dict[str, object]:
    """一次批量回测的完整请求：两个标的、给定成本、次日开盘成交。"""

    return {
        "strategy_version_id": version_id,
        "targets": {"mode": "list", "inst_ids": list(inst_ids), "group": None},
        "bar": "1d",
        "start_date": START,
        "end_date": END,
        "initial_capital": "10000",
        "quote_currency": "USDT",
        "position_size": "10000",
        "max_position_pct": "1",
        "costs": costs if costs is not None else COSTS,
        "funding_enabled": True,
        "execution_model": "next_open",
        "data_source": SOURCE,
    }


def test_phase4_backtest_batch_ranking_and_detail(
    client: TestClient, version_id: str, seeded: SeededMarket
) -> None:
    sent = request_body(version_id)
    created = client.post("/api/backtests", json=sent)
    assert created.status_code == 202, created.text
    first = created.json()
    assert first["status"] == "succeeded"
    assert first["inst_id"] in INST_IDS
    assert first["data_source"] == SOURCE
    assert first["is_proxy"] is False

    # 批量：两个标的各一条运行。
    listing = client.get("/api/backtests", params={"data_source": SOURCE})
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 2
    runs = listing.json()["items"]
    assert {run["inst_id"] for run in runs} == set(INST_IDS)
    assert all(run["metrics"] is not None for run in runs)

    # 排名：按收益降序、按回撤升序（回撤是正数幅度）。
    by_return = client.get(
        "/api/backtests/ranking", params={"data_source": SOURCE, "metric": "total_return_pct"}
    )
    assert by_return.status_code == 200, by_return.text
    rows = by_return.json()["items"]
    assert len(rows) == 2
    returns = [Decimal(row["total_return_pct"]) for row in rows]
    assert returns == sorted(returns, reverse=True)

    by_drawdown = client.get(
        "/api/backtests/ranking", params={"data_source": SOURCE, "metric": "max_drawdown_pct"}
    )
    drawdowns = [Decimal(row["max_drawdown_pct"]) for row in by_drawdown.json()["items"]]
    assert drawdowns == sorted(drawdowns)

    # 打开单条：组合级汇总在上，逐腿明细在下。按标的名取，避免依赖两条运行的同秒排序。
    run_id = next(run["run_id"] for run in runs if run["inst_id"] == "BTC-USDT")
    detail = client.get(f"/api/backtests/{run_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()

    assert body["request"] == sent
    portfolio = body["portfolio"]
    legs = body["legs"]
    trades = body["trades"]
    curve = body["equity_curve"]

    assert legs and trades, "该区间应当至少成交一条腿"
    assert {leg["inst_id"] for leg in legs} == {body["run"]["inst_id"]}
    for leg in legs:
        assert leg["inst_id"] == body["run"]["inst_id"]
        assert leg["side"] in ("long", "short")
        assert leg["entry_time"] <= leg["exit_time"]
        assert Decimal(leg["fee"]) >= 0
        assert leg["funding"] is None
    assert sum(leg["trade_count"] for leg in legs) == len(trades)

    # 逐腿贡献 = 该腿已实现盈亏 ÷ 初始资金。贡献之和对应的是「已实现」部分，收盘仍未
    # 平掉的仓位只在资金曲线里，所以不能拿它和总收益率比较，只能和多空合计对账。
    initial_capital = Decimal(body["run"]["metrics"]["initial_capital"])
    for leg in legs:
        assert (
            abs(
                Decimal(leg["contribution_pct"])
                - Decimal(leg["pnl"]) / initial_capital * Decimal(100)
            )
            < MILLIONTH
        )

    long_legs = [leg for leg in legs if leg["side"] == "long"]
    short_legs = [leg for leg in legs if leg["side"] == "short"]
    sum_long = sum((Decimal(leg["pnl"]) for leg in long_legs), Decimal(0))
    sum_short = sum((Decimal(leg["pnl"]) for leg in short_legs), Decimal(0))
    realized = sum_long + sum_short

    assert abs(Decimal(portfolio["long_pnl"]) - sum_long) < TOL
    assert abs(Decimal(portfolio["short_pnl"]) - sum_short) < TOL
    assert abs(realized - (Decimal(portfolio["long_pnl"]) + Decimal(portfolio["short_pnl"]))) < TOL

    total_contribution = sum(Decimal(leg["contribution_pct"]) for leg in legs)
    assert abs(total_contribution - realized / initial_capital * Decimal(100)) < MILLIONTH

    # 资金曲线：逐 bar，时间升序，根数与行情一致。
    times = [point["time"] for point in curve]
    assert times == sorted(times)
    assert len(times) == seeded.bar_count
    assert Decimal(curve[0]["equity"]) > 0

    # 逐笔交易带上了产品键与方向，可以按腿回放。
    for trade in trades:
        assert trade["product_key"] in {"BTC", "ETH"}
        assert trade["side"] in ("long", "short")
        assert trade["exit_time"] >= trade["entry_time"]
        assert trade["funding"] is None


def test_phase4_parameter_runs_are_comparable(client: TestClient, version_id: str) -> None:
    """换一组参数重跑是另一条结果，两条都留在列表里供人工对比（不标「最优」）。"""

    baseline = client.post("/api/backtests", json=request_body(version_id))
    assert baseline.status_code == 202, baseline.text

    changed_params = {"reversion_window": 2, "strength_window": 2, "pair_count": 1}
    version = get_version_by_id(version_id)
    assert version is not None
    changed_version = create_version(
        version.strategy_id,
        {"parameters": changed_params, "change_note": "换参数"},
    )
    assert changed_version is not None

    changed = client.post("/api/backtests", json=request_body(changed_version.current_version_id))
    assert changed.status_code == 202, changed.text

    listing = client.get("/api/backtests", params={"data_source": SOURCE}).json()
    assert listing["total"] == 4
    listed_params = [item["params"] for item in listing["items"]]
    assert listed_params.count(PARAMS) == 2
    assert listed_params.count(changed_params) == 2

    ranked = client.get(
        "/api/backtests/ranking", params={"data_source": SOURCE, "metric": "total_return_pct"}
    ).json()["items"]
    assert len(ranked) == 4
    # 只排序，没有任何「最优」标记字段；参数与运行标识让重复标的也能区分。
    assert set(ranked[0]) == {
        "run_id",
        "inst_id",
        "inst_type",
        "params",
        "total_return_pct",
        "max_drawdown_pct",
        "sharpe",
        "profit_factor",
        "trade_count",
    }
    assert len({row["run_id"] for row in ranked}) == 4
    ranked_params = [row["params"] for row in ranked]
    assert ranked_params.count(PARAMS) == 2
    assert ranked_params.count(changed_params) == 2

    detail = client.get(f"/api/backtests/{changed.json()['run_id']}").json()
    assert detail["run"]["params"] == changed_params


def test_phase4_same_request_reproduces_the_same_result(
    client: TestClient, version_id: str
) -> None:
    """同参数重跑：指标、逐笔交易与资金曲线逐字段相同（可复现的可观察证据）。"""

    first = client.post("/api/backtests", json=request_body(version_id, inst_ids=["BTC-USDT"]))
    second = client.post("/api/backtests", json=request_body(version_id, inst_ids=["BTC-USDT"]))
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text

    one = client.get(f"/api/backtests/{first.json()['run_id']}").json()
    two = client.get(f"/api/backtests/{second.json()['run_id']}").json()
    assert one["run"]["metrics"] == two["run"]["metrics"]
    assert one["equity_curve"] == two["equity_curve"]
    assert one["trades"] == two["trades"]
    assert one["legs"] == two["legs"]
    assert one["portfolio"] == two["portfolio"]


def test_phase4_delete_then_list(client: TestClient, version_id: str) -> None:
    created = client.post("/api/backtests", json=request_body(version_id, inst_ids=["BTC-USDT"]))
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    assert client.delete(f"/api/backtests/{run_id}").status_code == 204
    assert client.get(f"/api/backtests/{run_id}").status_code == 404
    assert client.get("/api/backtests", params={"data_source": SOURCE}).json()["total"] == 0
