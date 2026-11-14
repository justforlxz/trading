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

import csv
import io
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.mapping import decimal_str
from app.api.schemas import (
    BacktestBatchResponse,
    BacktestChartCandle,
    BacktestChartResponse,
    BacktestCosts,
    BacktestDetailResponse,
    BacktestEquityPoint,
    BacktestEquityResponse,
    BacktestLeg,
    BacktestMarker,
    BacktestMetrics,
    BacktestOverlay,
    BacktestOverlayPoint,
    BacktestPortfolio,
    BacktestRankingResponse,
    BacktestRankingRow,
    BacktestReplayPoint,
    BacktestReplayResponse,
    BacktestReplayTrade,
    BacktestRequest,
    BacktestRunListResponse,
    BacktestRunSummary,
    BacktestTrade,
    BacktestTradeListResponse,
    EquityPoint,
    GroupEquityPoint,
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
from app.core import InstrumentRef, ValidationError
from app.indicators import compute
from app.instrument import Instrument, list_instruments
from app.jobs import TargetScope, resolve_scope
from app.market import load_candles
from app.strategy import (
    InstanceRecord,
    StrategyVersionRecord,
    TargetLeg,
    TargetPortfolio,
    evaluate_replay,
    get_template,
    get_user_strategy,
    get_version_by_id,
    resolve_params,
)

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


@backtest_router.post("/backtests", response_model=BacktestBatchResponse, status_code=202)
def create_backtest(payload: BacktestRequest) -> BacktestBatchResponse:
    """按策略版本跑一次批量回测，每个标的各落一条运行，并返回等权组合净值。

    版本不存在返回 404；周期与版本不一致、标的超出版本范围、类别没有对应模板都返回
    400。目标组合仍由现有模板引擎按同一份历史行情逐时点回放，撮合与成本模型不变。
    每个运行都在同一事务里写入 `strategy_linked_backtests`，历史回测因此永远指向
    当时那个不可变版本。
    """

    version = get_version_by_id(payload.strategy_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"未找到策略版本 {payload.strategy_version_id}")
    if payload.bar != version.timeframe:
        raise ValidationError(
            f"回测周期必须与策略版本一致: 版本是 {version.timeframe}, 请求是 {payload.bar}"
        )
    instance = _version_instance(version)

    inst_ids = resolve_scope(
        TargetScope(
            mode=payload.targets.mode,
            inst_ids=tuple(payload.targets.inst_ids),
            group=payload.targets.group,
        )
    )
    outside = [inst_id for inst_id in inst_ids if inst_id not in version.instrument_ids]
    if outside:
        raise ValidationError(
            f"标的 {outside[0]} 不在策略版本 {version.version_id} 的标的集合内, "
            f"可选: {', '.join(version.instrument_ids)}"
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
            targets=_targets(
                outcome.targets,
                instrument,
                timeline,
                weight_cap,
                direction=version.direction,
            ),
            initial_capital=initial_capital,
            execution_model=payload.execution_model,
            costs=costs,
            settle=None,
        )
        run_spec = BacktestSpec(
            strategy_version_id=version.version_id,
            strategy_id=version.strategy_id,
            strategy_version=str(version.version),
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
    return BacktestBatchResponse(
        **_summary(records[0]).model_dump(),
        run_ids=[record.run_id for record in records],
        group_equity=_group_equity(records),
    )


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


@backtest_router.get("/backtests/{run_id}/chart", response_model=BacktestChartResponse)
def get_backtest_chart(run_id: str) -> BacktestChartResponse:
    """K 线、买卖标记与均线叠加；标记只从 `backtest_trades` 生成。"""

    record = _require_run(run_id)
    bars = _run_bars(record)
    times = [point.time for point in record.equity]
    selected = {bar.open_time: bar for bar in bars}
    candles = [_chart_candle(selected[moment]) for moment in times if moment in selected]
    return BacktestChartResponse(
        run_id=record.run_id,
        inst_id=record.inst_id,
        bar=record.bar,
        data_source=record.data_source,
        candles=candles,
        markers=_markers(record.trades),
        overlays=_overlays(bars, set(times)),
    )


@backtest_router.get("/backtests/{run_id}/equity", response_model=BacktestEquityResponse)
def get_backtest_equity(run_id: str) -> BacktestEquityResponse:
    """策略净值与回撤序列；引擎没有保存基准行情，因此 `benchmark` 为 null。"""

    record = _require_run(run_id)
    initial = record.metrics["initial_capital"]
    peak = initial
    points: list[BacktestEquityPoint] = []
    for point in record.equity:
        peak = max(peak, point.equity)
        drawdown = Decimal(0) if peak <= 0 else (point.equity - peak) / peak
        points.append(
            BacktestEquityPoint(
                time=point.time,
                equity=decimal_str(point.equity),
                benchmark_equity=None,
                drawdown=_ratio(drawdown),
            )
        )
    return BacktestEquityResponse(run_id=record.run_id, benchmark=None, points=points)


@backtest_router.get("/backtests/{run_id}/replay", response_model=BacktestReplayResponse)
def get_backtest_replay(run_id: str) -> BacktestReplayResponse:
    """按 K 线索引排列的回放点；只读本次运行保存的行情、净值与成交。"""

    record = _require_run(run_id)
    bars = _run_bars(record)
    by_time = {bar.open_time: bar for bar in bars}
    ma20 = _indicator_values(bars, 20)
    ma60 = _indicator_values(bars, 60)

    points: list[BacktestReplayPoint] = []
    index_by_time: dict[datetime, int] = {}
    previous = Decimal(0)
    for index, (point, exposure) in enumerate(zip(record.equity, record.exposure, strict=True)):
        index_by_time[point.time] = index
        delta = exposure.net_exposure - previous
        signal = "BUY" if delta > 0 else "SELL" if delta < 0 else "HOLD"
        position = point.equity * exposure.net_exposure
        candle = by_time.get(point.time)
        points.append(
            BacktestReplayPoint(
                index=index,
                time=point.time,
                close=None if candle is None else decimal_str(candle.close),
                equity=decimal_str(point.equity),
                cash=decimal_str(point.equity - position),
                position=decimal_str(position),
                signal=signal,
                indicators={
                    "ma20": None if point.time not in ma20 else decimal_str(ma20[point.time]),
                    "ma60": None if point.time not in ma60 else decimal_str(ma60[point.time]),
                },
            )
        )
        previous = exposure.net_exposure

    events: list[BacktestReplayTrade] = []
    for trade in record.trades:
        trade_id = _trade_id(trade)
        for kind, moment, side, price in (
            ("entry", trade.entry_time, _entry_side(trade.side), trade.entry_price),
            ("exit", trade.exit_time, _exit_side(trade.side), trade.exit_price),
        ):
            index = index_by_time.get(moment)
            if index is None:
                continue
            events.append(
                BacktestReplayTrade(
                    index=index,
                    trade_id=trade_id,
                    kind=kind,
                    side=side,
                    price=decimal_str(price),
                    qty=decimal_str(trade.qty),
                )
            )
    events.sort(key=lambda item: (item.index, item.kind, item.trade_id))
    return BacktestReplayResponse(
        run_id=record.run_id,
        bar=record.bar,
        points=points,
        trades=events,
    )


@backtest_router.get("/backtests/{run_id}/trades", response_model=BacktestTradeListResponse)
def list_backtest_trades(
    run_id: str,
    side: str | None = Query(None, pattern="^(long|short)$"),
    result: str | None = Query(None, pattern="^(profit|loss)$"),
    inst_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> BacktestTradeListResponse:
    """按方向、盈亏结果与标的筛选交易明细，分页返回本页与总条数。"""

    record = _require_run(run_id)
    filtered = _filter_trades(record, side=side, result=result, inst_id=inst_id)
    page = filtered[offset : offset + limit]
    return BacktestTradeListResponse(
        run_id=record.run_id,
        items=[_trade(trade) for trade in page],
        total=len(filtered),
        limit=limit,
        offset=offset,
    )


@backtest_router.get(
    "/backtests/{run_id}/trades.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def export_backtest_trades(
    run_id: str,
    side: str | None = Query(None, pattern="^(long|short)$"),
    result: str | None = Query(None, pattern="^(profit|loss)$"),
    inst_id: str | None = Query(None),
) -> Response:
    """导出当前筛选条件下的交易明细；UTF-8 带 BOM，列顺序固定。"""

    record = _require_run(run_id)
    filtered = _filter_trades(record, side=side, result=result, inst_id=inst_id)
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(
        [
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
    )
    for trade in filtered:
        writer.writerow(
            [
                trade.inst_id,
                "多头" if trade.side == "long" else "空头",
                _iso_z(trade.entry_time),
                decimal_str(trade.entry_price),
                _iso_z(trade.exit_time),
                decimal_str(trade.exit_price),
                decimal_str(trade.qty),
                decimal_str(trade.fee),
                "",
                decimal_str(trade.slippage),
                decimal_str(trade.pnl - trade.fee),
                trade.reason,
            ]
        )
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="backtest-{record.run_id}-trades.csv"'
        },
    )


def _require_run(run_id: str) -> BacktestRunRecord:
    """取一次已保存的运行；不存在时按统一错误格式回答 404。"""

    record = get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到回测记录 {run_id}")
    return record


def _version_instance(version: StrategyVersionRecord) -> InstanceRecord:
    """把不可变策略版本投影成模板引擎可执行的实例。

    用户策略的 `category` 就是模板登记名（方向性 / 相对价值这类组合方式）；版本的
    `parameters` 是这套模板的参数。投影只发生在内存里，不写 `strategy_instances`：
    回测的历史事实由 `backtest_runs` 与 `strategy_linked_backtests` 保存，不依赖实例表。
    """

    strategy = get_user_strategy(version.strategy_id)
    if strategy is None:
        raise ValidationError(f"未找到策略版本 {version.version_id} 所属的策略")
    try:
        template = get_template(strategy.category)
    except ValidationError as exc:
        raise ValidationError(f"策略类别 {strategy.category!r} 没有对应的回测模板: {exc}") from exc
    params = resolve_params(template.param_schema, dict(version.parameters))
    return InstanceRecord(
        instance_id=version.version_id,
        strategy_id=template.meta.name,
        strategy_version=str(version.version),
        name=strategy.name,
        bar=version.timeframe,
        params=params,
        inst_ids=version.instrument_ids,
        lifecycle_status="strategy_generation",
        enabled=True,
        execution_mode="manual",
        latest_signal_at=None,
        created_at=version.created_at,
        updated_at=version.created_at,
    )


def _run_bars(record: BacktestRunRecord) -> list[Any]:
    """读回本次运行区间与数据源内的 K 线；只查历史库，不访问实时行情。

    结束时刻是「结束日当天 23:59:59Z」，而 `load_candles` 的窗口是半开区间；加一秒
    才能把恰好落在该秒上的最后一根 K 线包含进来。
    """

    start, end = _window(record.start_date, record.end_date)
    return load_candles(
        record.inst_id,
        record.bar,
        start=start,
        end=end + timedelta(seconds=1),
        source=record.data_source,
    )


def _chart_candle(bar: Any) -> BacktestChartCandle:
    """行情模块的一根 K 线 → 图表契约；来源与是否收盘原样保留。"""

    return BacktestChartCandle(
        time=bar.open_time,
        open=decimal_str(bar.open),
        high=decimal_str(bar.high),
        low=decimal_str(bar.low),
        close=decimal_str(bar.close),
        volume=decimal_str(bar.volume),
        is_complete=bool(bar.confirm),
        source=bar.source,
    )


def _markers(trades: Sequence[Any]) -> list[BacktestMarker]:
    """每笔完整交易生成入场与出场两个标记；标记只来自 `backtest_trades`。

    多头入场的买卖方向是买入、出场是卖出；空头相反。盈亏与退出原因只放在出场标记
    上：同一笔交易的盈亏说两次没有意义，入场时也还没有结果。
    """

    markers: list[BacktestMarker] = []
    for trade in trades:
        trade_id = _trade_id(trade)
        markers.append(
            BacktestMarker(
                trade_id=trade_id,
                kind="entry",
                time=trade.entry_time,
                price=decimal_str(trade.entry_price),
                side=_entry_side(trade.side),
                qty=decimal_str(trade.qty),
            )
        )
        markers.append(
            BacktestMarker(
                trade_id=trade_id,
                kind="exit",
                time=trade.exit_time,
                price=decimal_str(trade.exit_price),
                side=_exit_side(trade.side),
                qty=decimal_str(trade.qty),
                pnl=decimal_str(trade.pnl),
                reason=trade.reason,
            )
        )
    markers.sort(key=lambda item: (item.time, item.kind != "entry", item.trade_id))
    return markers


def _overlays(bars: Sequence[Any], times: set[datetime]) -> list[BacktestOverlay]:
    """由本次运行已保存的 K 线计算 MA20 / MA60，只保留净值时间轴上的点。"""

    overlays: list[BacktestOverlay] = []
    for period in (20, 60):
        values = _indicator_values(bars, period)
        overlays.append(
            BacktestOverlay(
                name=f"MA{period}",
                points=[
                    BacktestOverlayPoint(time=moment, value=decimal_str(values[moment]))
                    for moment in sorted(times)
                    if moment in values
                ],
            )
        )
    return overlays


def _indicator_values(bars: Sequence[Any], period: int) -> dict[datetime, Decimal]:
    """按周期算 SMA，返回「时刻 → 值」；窗口未成形的点不出现。"""

    series = compute("sma", bars, {"period": period})
    return {
        point.time: point.values["sma"]
        for point in series.points
        if point.values.get("sma") is not None
    }


def _ratio(value: Decimal) -> str:
    """比率按契约的小数位收口；正负号就是回撤方向，不改写为百分比。"""

    return decimal_str(value)


def _entry_side(side: str) -> str:
    return "buy" if side == "long" else "sell"


def _exit_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def _trade_id(trade: Any) -> str:
    """稳定标识：产品键 + 开仓与平仓时刻 + 持仓方向 + 数量。

    同一标的可以在同一根 K 线上分批建立方向相同的仓位，只用开仓时刻与方向会让
    这些交易共用一个标识，回放和图表就分不清是哪一笔。平仓时刻与数量一起参与，
    才能在保存下来的成交之间保持唯一。
    """

    return (
        f"{trade.product_key}:{trade.entry_time.isoformat()}:"
        f"{trade.exit_time.isoformat()}:{trade.side}:{decimal_str(trade.qty)}"
    )


def _filter_trades(
    record: BacktestRunRecord,
    *,
    side: str | None,
    result: str | None,
    inst_id: str | None,
) -> list[Any]:
    """按方向、净盈亏结果与标的筛选；结果按「价格盈亏 − 手续费」判定。"""

    selected: list[Any] = []
    for trade in record.trades:
        if side is not None and trade.side != side:
            continue
        net = trade.pnl - trade.fee
        if result == "profit" and net <= 0:
            continue
        if result == "loss" and net >= 0:
            continue
        if inst_id is not None and trade.inst_id != inst_id:
            continue
        selected.append(trade)
    return selected


def _iso_z(value: datetime) -> str:
    """CSV 里的时刻统一成 UTC、秒精度、带 `Z`。"""

    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _group_equity(records: Sequence[BacktestRunRecord]) -> list[GroupEquityPoint]:
    """把同一批的成员运行合成等权组合净值。

    每个成员先用自己的首点归一化，再在每个时刻对已开始的成员取平均；成员在某个时刻
    没有曲线点时沿用自己上一个有效值。这样不同标的的初始资金和日线起点不同也能合成，
    且不会为缺失成员补一条假曲线。
    """

    members: list[tuple[Decimal, dict[datetime, Decimal]]] = []
    for record in records:
        if not record.equity:
            continue
        base = record.equity[0].equity
        if base <= 0:
            continue
        members.append((base, {point.time: point.equity for point in record.equity}))
    if not members:
        return []

    timeline = sorted({moment for _, points in members for moment in points})
    last: list[Decimal | None] = [None] * len(members)
    combined: list[GroupEquityPoint] = []
    for moment in timeline:
        total = Decimal(0)
        count = 0
        for index, (base, points) in enumerate(members):
            value = points.get(moment)
            if value is not None:
                last[index] = value
            if last[index] is not None:
                total += last[index] / base
                count += 1
        if count:
            combined.append(GroupEquityPoint(time=moment, nav=decimal_str(total / Decimal(count))))
    return combined


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
    *,
    direction: str,
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
            and (direction == "long_short" or leg.side == direction.split("_")[0])
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
        strategy_version_id=record.strategy_version_id,
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
        trade_id=_trade_id(trade),
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
        slippage=decimal_str(trade.slippage),
        funding=None,
        pnl=decimal_str(trade.pnl),
        net_pnl=decimal_str(trade.pnl - trade.fee),
        reason=trade.reason,
    )


def _request(record: BacktestRunRecord) -> BacktestRequest:
    """落库的请求原样还原成契约模型；坏数据属于「不该发生」，直接判错。"""

    payload = dict(record.request)
    payload["strategy_version_id"] = record.strategy_version_id or ""
    return BacktestRequest.model_validate(payload)


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
