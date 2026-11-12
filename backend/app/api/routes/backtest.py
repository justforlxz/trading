"""回测域端点：发起回测、列出结果、排序、明细与删除。

端点只做三件事：把契约输入换成域调用、把域记录投影成契约模型、把域异常交给统一
错误处理。回测怎么跑、指标怎么算、结果怎么落库都在 `app.backtest` 里。

## 一次回测只跑一个标的

批量回测按标的分成多条运行，每条记录一个标的：排行榜与结果列表要按标的排出一行，
而一次运行的身份里必须带着标的名，否则「这一行是哪只标的」只能靠猜。请求里的
`targets` 因此决定「这些标的中哪些各跑一次」，顺序按 `app.jobs.resolve_scope` 的
口径。发起接口返回其中第一条，完整清单由 `GET /backtests` 给出。

## 目标组合来自策略回放

每个时点的目标组合由策略实例在**同一个数据源**上回放得出（`strategy.evaluate_replay`
的 `source` 固定为请求的 `data_source`）：回测一次只允许一个数据源，跨源拼接会让
时间轴与净值失去意义。回放给出的是多腿组合，本端点只取当前这条运行对应标的的那条腿，
因此同一次批量里每个标的各用自己的资金与自己的腿，互相不共享账户。

## 仓位上限

`position_size` 与 `max_position_pct` 是用户给的上限，取更紧的那个压住策略给出的
目标权重：`min(腿权重, position_size / 初始资金, max_position_pct)`。策略说「想拿多
少权重」，用户说「最多能拿多少」，两者取小。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.mapping import decimal_str
from app.api.schemas import (
    BacktestCosts,
    BacktestDetailResponse,
    BacktestLeg,
    BacktestMetrics,
    BacktestPortfolio,
    BacktestRankingResponse,
    BacktestRankingRow,
    BacktestRequest,
    BacktestRunListResponse,
    BacktestRunSummary,
    BacktestTrade,
    EquityPoint,
    RankingMetric,
)
from app.api.schemas.common import DataSource
from app.backtest import (
    BacktestInput,
    BacktestRunHeader,
    BacktestRunPlan,
    BacktestRunRecord,
    BacktestSpec,
    CostModel,
    data_fingerprint,
    delete_run,
    get_run,
    list_runs,
    rank_rows,
    run_backtest,
    save_runs,
)
from app.core import Conflict, InstrumentRef, ValidationError
from app.instrument import Instrument, list_instruments
from app.jobs import TargetScope, resolve_scope
from app.market import load_candles
from app.strategy import TargetLeg, TargetPortfolio, evaluate_replay, get_instance

__all__ = ["backtest_router"]

backtest_router = APIRouter(tags=["backtest"])

#: 契约里的排序指标 → 指标模块的内部键。两套名字各自在自己的层里成立：契约用
#: `_pct` 表明已换成百分数，域内用比率（0.12 表示 12%）。
_RANKING_METRICS: dict[str, str] = {
    "total_return_pct": "total_return",
    "max_drawdown_pct": "max_drawdown",
    "sharpe": "sharpe",
    "profit_factor": "profit_factor",
}

#: 一天里最后一个时刻之前的结束日：结束日包含当天，因此取 23:59:59Z。
_END_OF_DAY = time(23, 59, 59)
_HUNDRED = Decimal(100)


@backtest_router.get("/backtests/ranking", response_model=BacktestRankingResponse)
def get_backtest_ranking(
    data_source: DataSource = Query(...),
    metric: RankingMetric = Query("total_return_pct"),
    limit: int = Query(50, ge=1, le=500),
) -> BacktestRankingResponse:
    """按一个指标给该数据源的历史回测排序。

    只排序，不标「最优」：把历史收益最高的那一行标成最优，等于把「过去涨得好」写成
    「以后也该选它」。`max_drawdown_pct` 是正数幅度，按它排序时最小的排在最前。
    """

    headers, _ = list_runs(data_source, limit=limit)
    ranked = rank_rows(
        headers,
        metric=_RANKING_METRICS[metric],
        metrics_of=lambda header: header.metrics,
    )
    return BacktestRankingResponse(
        data_source=data_source,
        metric=metric,
        items=[_ranking_row(header) for header in ranked],
    )


@backtest_router.post("/backtests", response_model=BacktestRunSummary, status_code=202)
def create_backtest(payload: BacktestRequest) -> BacktestRunSummary:
    """按请求跑一次批量回测，每个标的各落一条运行；返回其中第一条。

    实例不存在返回 404，已停用返回 409（与目标组合回放同一口径）：静默跳过一个停用的
    实例会让「没有信号」与「没跑」混成同一件事。
    """

    instance = get_instance(payload.strategy_instance_id)
    if instance is None:
        raise HTTPException(
            status_code=404, detail=f"未找到策略实例 {payload.strategy_instance_id}"
        )
    if not instance.enabled:
        raise Conflict(f"策略实例 {instance.instance_id} 已停用, 不能回测")
    if payload.bar != instance.bar:
        raise ValidationError(
            f"回测周期必须与策略实例一致: 实例是 {instance.bar}, 请求是 {payload.bar}"
        )

    inst_ids = resolve_scope(
        TargetScope(
            mode=payload.targets.mode,
            inst_ids=tuple(payload.targets.inst_ids),
            group=payload.targets.group,
        )
    )
    outside = [inst_id for inst_id in inst_ids if inst_id not in instance.inst_ids]
    if outside:
        raise ValidationError(
            f"标的 {outside[0]} 不在策略实例 {instance.instance_id} 的标的集合内, "
            f"可选: {', '.join(instance.inst_ids)}"
        )

    start, end = _window(payload.start_date, payload.end_date)
    costs = _cost_model(payload.costs)
    initial_capital = Decimal(payload.initial_capital)
    weight_cap = _weight_cap(payload, initial_capital)

    known = {row.symbol: row for row in list_instruments()}
    instruments = [known[inst_id] for inst_id in inst_ids]
    outcome = evaluate_replay(instance, start=start, end=end, source=payload.data_source)
    request_payload = payload.model_dump(mode="json")

    # 先把每个标的都算成一份待落库的计划：任何一步失败时数据库里还没有任何一行。
    plans: list[BacktestRunPlan] = []
    for instrument in instruments:
        bars = load_candles(
            instrument.symbol,
            payload.bar,
            start=start,
            end=end,
            source=payload.data_source,
        )
        if not bars:
            raise ValidationError(
                f"标的 {instrument.symbol} 在 {payload.start_date} ~ {payload.end_date} "
                f"没有 {payload.bar} 周期的 {payload.data_source} 行情"
            )
        by_key = {instrument.product_key: bars}
        timeline = {bar.open_time for bar in bars}
        run_request = BacktestInput(
            bars=by_key,
            instruments={instrument.product_key: _instrument_ref(instrument)},
            targets=_targets(outcome.targets, instrument, timeline, weight_cap),
            initial_capital=initial_capital,
            execution_model=payload.execution_model,
            costs=costs,
            settle=None,
        )
        run_spec = BacktestSpec(
            strategy_instance_id=instance.instance_id,
            strategy_id=instance.strategy_id,
            strategy_version=instance.strategy_version,
            params=dict(instance.params),
            bar=payload.bar,
            start_date=payload.start_date,
            end_date=payload.end_date,
            data_source=payload.data_source,
            inst_id=instrument.symbol,
            inst_type=instrument.inst_type,
            request=request_payload,
            data_fingerprint=data_fingerprint(by_key, payload.data_source),
            execution_model=payload.execution_model,
            initial_capital=initial_capital,
            costs=costs,
        )
        plans.append(
            BacktestRunPlan(
                request=run_request,
                spec=run_spec,
                result=run_backtest(run_request),
            )
        )

    # 整批一个事务：要么全部落库，要么一行都不留。
    records = save_runs(plans)
    return _summary(records[0])


@backtest_router.get("/backtests", response_model=BacktestRunListResponse)
def list_backtests(
    data_source: DataSource = Query(...),
    limit: int = Query(50, ge=1, le=200),
) -> BacktestRunListResponse:
    """按数据源列出历史回测（新到旧）。数据源必填，不做跨源聚合。"""

    headers, total = list_runs(data_source, limit=limit)
    return BacktestRunListResponse(
        data_source=data_source,
        items=[_summary(header) for header in headers],
        total=total,
    )


@backtest_router.get("/backtests/{run_id}", response_model=BacktestDetailResponse)
def get_backtest(run_id: str) -> BacktestDetailResponse:
    """一次回测的完整结果：组合级汇总、逐腿明细、逐笔成交与资金曲线。"""

    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到回测记录 {run_id}")
    initial_capital = record.metrics["initial_capital"]
    return BacktestDetailResponse(
        run=_summary(record),
        request=_request(record),
        portfolio=_portfolio(record),
        legs=_legs(record.trades, initial_capital),
        trades=[_trade(trade) for trade in record.trades],
        equity_curve=[
            EquityPoint(time=point.time, equity=decimal_str(point.equity))
            for point in record.equity
        ],
    )


@backtest_router.delete("/backtests/{run_id}", status_code=204, response_model=None)
def delete_backtest(run_id: str) -> None:
    """删除一次回测及其逐笔交易与资金曲线。"""

    if not delete_run(run_id):
        raise HTTPException(status_code=404, detail=f"未找到回测记录 {run_id}")


def _window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """业务日期区间 → UTC 时刻区间：起点当天零点，终点当天 23:59:59Z。"""

    if start_date > end_date:
        raise ValidationError(f"回测区间起点 {start_date} 晚于终点 {end_date}")
    return (
        datetime.combine(start_date, time.min, tzinfo=UTC),
        datetime.combine(end_date, _END_OF_DAY, tzinfo=UTC),
    )


def _cost_model(costs: BacktestCosts) -> CostModel:
    """契约成本 → 域成本模型；四项都参与成交价或费率，没有一项被忽略。"""

    values = {
        "maker_fee_bps": Decimal(costs.maker_fee_bps),
        "taker_fee_bps": Decimal(costs.taker_fee_bps),
        "slippage_bps": Decimal(costs.slippage_bps),
        "spread_bps": Decimal(costs.spread_bps),
    }
    for name, value in values.items():
        if not value.is_finite() or value < 0:
            raise ValidationError(f"成本 {name} 必须是非负有限数, 实际 {value}")
    return CostModel(**values)


def _weight_cap(payload: BacktestRequest, initial_capital: Decimal) -> Decimal:
    """用户给的两条上限里更紧的那个：每笔金额折算成权重，再与最大持仓比例取小。

    `initial_capital` 必须先验成正有限数再做除法：契约的十进制正侧允许 `"0"`，而
    `0` 做除数抛的是 `ArithmeticError`，会绕过域错误分派变成 500。
    """

    if not initial_capital.is_finite() or initial_capital <= 0:
        raise ValidationError(f"初始资金必须是正有限数, 实际 {initial_capital}")
    position_size = Decimal(payload.position_size)
    max_position_pct = Decimal(payload.max_position_pct)
    if not position_size.is_finite() or position_size <= 0:
        raise ValidationError(f"每笔交易金额必须是正有限数, 实际 {position_size}")
    if not max_position_pct.is_finite() or not Decimal(0) < max_position_pct <= Decimal(1):
        raise ValidationError(f"最大持仓比例必须在 (0, 1] 内, 实际 {max_position_pct}")
    return min(position_size / initial_capital, max_position_pct)


def _targets(
    series: Sequence[TargetPortfolio],
    instrument: Instrument,
    timeline: set[datetime],
    weight_cap: Decimal,
) -> tuple[TargetPortfolio, ...]:
    """把完整目标组合序列收窄成本次运行只含一条腿的序列。

    只保留当前标的的腿，并按 `weight_cap` 压住权重；该时刻没有这条腿时给出空组合
    （空组合是「该时点不持仓」，与「该时点没有信号」在回测里是同一件事）。
    """

    rounds: list[TargetPortfolio] = []
    for target in series:
        if target.as_of not in timeline:
            continue
        legs = tuple(
            TargetLeg(
                product_key=leg.product_key,
                side=leg.side,
                target_weight=min(leg.target_weight, weight_cap),
                reason=leg.reason,
            )
            for leg in target.legs
            if leg.product_key == instrument.product_key
        )
        rounds.append(TargetPortfolio(as_of=target.as_of, legs=legs))
    return tuple(rounds)


def _instrument_ref(row: Instrument) -> InstrumentRef:
    """标的表实体 → 引擎要的静态快照（数量换算只用到 lot_size 与 ct_val）。"""

    return InstrumentRef(
        inst_id=row.symbol,
        inst_type=row.inst_type,
        base_ccy=row.base_currency,
        quote_ccy=row.quote_currency,
        state=row.trading_status,
        tick_size=row.tick_size,
        lot_size=row.lot_size,
        min_size=row.min_order_size,
        list_time=row.listing_time,
        settle_ccy=row.settle_ccy or "",
        ct_val=row.ct_val,
        ct_mult=row.ct_mult,
        ct_type=row.ct_type or "",
        max_lever=row.max_lever,
    )


def _summary(record: BacktestRunRecord | BacktestRunHeader) -> BacktestRunSummary:
    """运行记录 → 列表项。全部回测都是同步跑完才落库，状态恒为 `succeeded`。"""

    return BacktestRunSummary(
        run_id=record.run_id,
        status="succeeded",
        strategy_instance_id=record.strategy_instance_id,
        params=dict(record.params),
        data_source=record.data_source,
        inst_id=record.inst_id,
        inst_type=record.inst_type,
        is_proxy=record.data_source == "us_equity_proxy",
        bar=record.bar,
        start_date=record.start_date,
        end_date=record.end_date,
        symbol_count=1,
        created_at=record.created_at,
        finished_at=None,
        metrics=_metrics(record),
        error_message=None,
    )


def _metrics(record: BacktestRunRecord | BacktestRunHeader) -> BacktestMetrics:
    """域指标 → 契约指标：比率换成百分数，交易次数换成整数。

    资金费覆盖率与缺口数没有随结果落库（`backtest_runs` 只存资金费合计），因此返回
    null 而不是 0：0 会被读成「一点都没缺」，null 才是「这一版没记」。
    """

    metrics = record.metrics
    return BacktestMetrics(
        initial_capital=decimal_str(metrics["initial_capital"]),
        final_capital=decimal_str(metrics["final_capital"]),
        total_return_pct=_percent(metrics["total_return"]),
        annualized_return_pct=_percent(metrics["annualized_return"]),
        max_drawdown_pct=_percent(metrics["max_drawdown"]),
        win_rate=decimal_str(metrics["win_rate"]),
        payoff_ratio=decimal_str(metrics["profit_loss_ratio"]),
        profit_factor=decimal_str(metrics["profit_factor"]),
        sharpe=decimal_str(metrics["sharpe"]),
        trade_count=int(metrics["trade_count"]),
        avg_holding_hours=decimal_str(metrics["average_holding_hours"]),
        max_single_win=decimal_str(metrics["max_single_win"]),
        max_single_loss=decimal_str(metrics["max_single_loss"]),
        funding_total=decimal_str(record.funding_total),
        funding_coverage_pct=None,
        funding_missing_count=None,
    )


def _percent(ratio: Decimal) -> str:
    """比率（0.124）→ 百分数（12.4）。"""

    return decimal_str(ratio * _HUNDRED)


def _portfolio(record: BacktestRunRecord) -> BacktestPortfolio:
    """组合级四项：净敞口、每腿胜率、多腿合计盈亏、空腿合计盈亏。"""

    return BacktestPortfolio(
        net_exposure=decimal_str(record.portfolio.net_exposure),
        leg_win_rate={
            key: decimal_str(value) for key, value in record.portfolio.leg_win_rate.items()
        },
        long_pnl=decimal_str(record.portfolio.long_pnl),
        short_pnl=decimal_str(record.portfolio.short_pnl),
    )


def _legs(trades: Sequence[Any], initial_capital: Decimal) -> list[BacktestLeg]:
    """逐笔交易按「产品键 + 方向」汇总成逐腿明细，按产品键与方向排序。

    一条腿的区间取第一笔开仓到最后一笔平仓；贡献是这条腿的已实现盈亏占初始资金的
    百分比。回测结束时未平掉的仓位只在资金曲线里，不在逐笔交易里，因此各腿贡献相加
    可能小于总收益率。
    """

    grouped: dict[tuple[str, str], list[Any]] = {}
    for trade in trades:
        grouped.setdefault((trade.product_key, trade.side), []).append(trade)

    legs: list[BacktestLeg] = []
    for key in sorted(grouped):
        rows = grouped[key]
        pnl = sum((row.pnl for row in rows), Decimal(0))
        fee = sum((row.fee for row in rows), Decimal(0))
        legs.append(
            BacktestLeg(
                product_key=key[0],
                inst_id=rows[0].inst_id,
                inst_type=rows[0].inst_type,
                side=key[1],
                trade_count=len(rows),
                entry_time=min(row.entry_time for row in rows),
                exit_time=max(row.exit_time for row in rows),
                fee=decimal_str(fee),
                funding=None,
                pnl=decimal_str(pnl),
                contribution_pct=_percent(pnl / initial_capital),
            )
        )
    return legs


def _trade(trade: Any) -> BacktestTrade:
    """一条完整交易 → 契约模型；逐腿资金费当前不拆分，`funding` 为 null。

    `trade_id` 由「产品键 + 开仓时刻 + 方向」拼成：同一份结果读两次得到同一个标识，
    与落库时按序号生成的标识一样稳定。
    """

    return BacktestTrade(
        trade_id=f"{trade.product_key}:{trade.entry_time.isoformat()}:{trade.side}",
        product_key=trade.product_key,
        inst_id=trade.inst_id,
        inst_type=trade.inst_type,
        side=trade.side,
        qty=decimal_str(trade.qty),
        entry_time=trade.entry_time,
        entry_price=decimal_str(trade.entry_price),
        exit_time=trade.exit_time,
        exit_price=decimal_str(trade.exit_price),
        fee=decimal_str(trade.fee),
        funding=None,
        pnl=decimal_str(trade.pnl),
        reason=trade.reason,
    )


def _request(record: BacktestRunRecord) -> BacktestRequest:
    """落库的请求原样还原成契约模型；坏数据属于「不该发生」，直接判错。"""

    return BacktestRequest.model_validate(dict(record.request))


def _ranking_row(header: BacktestRunHeader) -> BacktestRankingRow:
    """排行榜的一行：标的名 + 四项指标 + 交易次数。"""

    metrics = header.metrics
    return BacktestRankingRow(
        run_id=header.run_id,
        inst_id=header.inst_id,
        inst_type=header.inst_type,
        params=dict(header.params),
        total_return_pct=_percent(metrics["total_return"]),
        max_drawdown_pct=_percent(metrics["max_drawdown"]),
        sharpe=decimal_str(metrics["sharpe"]),
        profit_factor=decimal_str(metrics["profit_factor"]),
        trade_count=int(metrics["trade_count"]),
    )
