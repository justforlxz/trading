"""回测结果的服务编排：算指标 → 落成三张表 → 读回可回放的记录。

本模块只做编排与事务边界，计算全部交给纯函数：

- 逐腿交易由 `metrics.closed_trades` 从成交序列折出；
- 13 个标的级指标由 `metrics.compute_metrics` 算；
- 净敞口序列与四项组合级指标由 `metrics.exposure_series` / `metrics.portfolio_metrics` 算。

## 可复现

`result_hash` 是**可复现输入**的摘要，覆盖策略版本、参数、数据区间、数据指纹、执行模型、
数据源与成本假设。同一份输入重跑必然得到同一个 `result_hash`；改动其中任何一项，摘要
都会变。数据指纹由 `data_fingerprint` 从实际喂进引擎的 K 线算出，因此「同一区间但行情
被修正过」不会与旧结果混成同一个标识。

## 三张表的分工

`backtest_runs` 存身份与汇总，`backtest_trades` 存逐腿完整交易，`backtest_equity` 存逐 bar
的净值与净敞口。写侧一次事务写完三层，读侧按 run 一次取回，因此「按腿回放」只需要一个
`run_id`。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from app.backtest.costs import CostModel, decimal_text
from app.backtest.engine import EXECUTION_MODELS, BacktestInput, BacktestResult, EquityPoint
from app.backtest.metrics import (
    ClosedTrade,
    ExposurePoint,
    PortfolioMetrics,
    closed_trades,
    compute_metrics,
    default_annualization_factor,
    exposure_series,
    portfolio_metrics,
    quantize_money,
)
from app.backtest.model import BacktestEquityRow, BacktestRunRow, BacktestTradeRow
from app.core import Bar, ValidationError
from app.db import session_scope
from app.shared import CANONICAL_BARS
from app.strategy import StrategyLinkedBacktestRow

__all__ = [
    "BacktestRunHeader",
    "BacktestRunPlan",
    "BacktestRunRecord",
    "BacktestSpec",
    "data_fingerprint",
    "delete_run",
    "get_run",
    "latest_linked_backtests",
    "latest_run",
    "list_runs",
    "save_run",
    "save_runs",
]

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class BacktestSpec:
    """一次回测的可复现输入中，引擎之外由调用方给出的那部分。

    `data_fingerprint` 由 `data_fingerprint(bars, data_source)` 算出后传入：服务层不重复
    读行情，指纹必须来自实际喂进引擎的那份数据。
    """

    strategy_instance_id: str
    strategy_id: str
    strategy_version: str
    params: Mapping[str, Any]
    bar: str
    start_date: date
    end_date: date
    data_source: str
    inst_id: str
    inst_type: str
    request: Mapping[str, Any]
    data_fingerprint: str
    execution_model: str
    initial_capital: Decimal
    costs: CostModel

    def __post_init__(self) -> None:
        for name in (
            "strategy_instance_id",
            "strategy_id",
            "strategy_version",
            "data_source",
            "inst_id",
            "inst_type",
            "data_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"回测的 {name} 不能为空")
        if self.bar not in CANONICAL_BARS:
            raise ValidationError(
                f"回测的 bar 必须是 {list(CANONICAL_BARS)} 之一, 实际 {self.bar!r}"
            )
        if self.execution_model not in EXECUTION_MODELS:
            raise ValidationError(
                f"未知执行模型 {self.execution_model!r}; 可选 {list(EXECUTION_MODELS)}"
            )
        if self.start_date > self.end_date:
            raise ValidationError(f"回测区间起点 {self.start_date} 晚于终点 {self.end_date}")
        if not isinstance(self.initial_capital, Decimal):
            raise ValidationError(
                f"初始资金必须是 Decimal, 实际 {type(self.initial_capital).__name__}"
            )
        if not self.initial_capital.is_finite() or self.initial_capital <= ZERO:
            raise ValidationError(f"初始资金必须是正有限数, 实际 {self.initial_capital}")
        if not isinstance(self.params, Mapping):
            raise ValidationError("策略参数必须是映射")
        try:
            json.dumps(self.params, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"策略参数必须可 JSON 序列化:{exc}") from exc
        if not isinstance(self.request, Mapping):
            raise ValidationError("回测请求必须是映射")
        try:
            json.dumps(self.request, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"回测请求必须可 JSON 序列化:{exc}") from exc


@dataclass(frozen=True, slots=True)
class BacktestRunRecord:
    """一次已落库的回测：身份、汇总、逐腿交易与逐 bar 曲线。

    `equity` 与 `exposure` 一一对应（同一根 bar 的净值和该 bar 在用的净敞口）。
    `request` 是发起这次回测的完整请求（原样存取），详情接口按它重放同一份输入。
    """

    run_id: str
    strategy_instance_id: str
    strategy_id: str
    strategy_version: str
    params: Mapping[str, Any]
    bar: str
    start_date: date
    end_date: date
    data_source: str
    inst_id: str
    inst_type: str
    request: Mapping[str, Any]
    data_fingerprint: str
    execution_model: str
    costs: Mapping[str, Any]
    metrics: Mapping[str, Decimal]
    portfolio: PortfolioMetrics
    funding_total: Decimal
    result_hash: str
    created_at: datetime
    trades: tuple[ClosedTrade, ...]
    equity: tuple[EquityPoint, ...]
    exposure: tuple[ExposurePoint, ...]


def data_fingerprint(
    bars: Mapping[str, Sequence[Bar]],
    data_source: str,
) -> str:
    """行情指纹：产品键 + 每根 K 线的时刻、开高低收、成交量与来源。

    排序后序列化，因此映射的插入顺序不影响指纹；同一份行情得到同一个指纹，行情被修正
    过（哪怕只差一个收盘价）就得到另一个。`data_source` 一并纳入：同一批价格从不同来源
    取到，本身就不该算成同一份可复现输入。
    """

    if not isinstance(data_source, str) or not data_source.strip():
        raise ValidationError("行情指纹的 data_source 不能为空")
    payload: dict[str, Any] = {
        "data_source": data_source,
        "bars": [
            [
                key,
                [
                    [
                        candle.open_time.isoformat(),
                        decimal_text(candle.open),
                        decimal_text(candle.high),
                        decimal_text(candle.low),
                        decimal_text(candle.close),
                        decimal_text(candle.volume),
                        candle.confirm,
                        candle.source,
                        candle.market_session,
                    ]
                    for candle in sorted(rows, key=lambda item: item.open_time)
                ],
            ]
            for key, rows in sorted(bars.items())
        ],
    }
    return _sha256(payload)


@dataclass(frozen=True, slots=True)
class BacktestRunPlan:
    """一次已经跑完、尚未落库的回测：引擎输入 + 可复现输入 + 结果。

    批量回测先把每个标的都算成一份计划，全部成功之后才一起落库：任何一步失败都不会
    在库里留下「前几个标的已写入」的半批结果。
    """

    request: BacktestInput
    spec: BacktestSpec
    result: BacktestResult


def save_run(
    request: BacktestInput,
    spec: BacktestSpec,
    result: BacktestResult,
) -> BacktestRunRecord:
    """把一次已经跑完的回测算成指标并落库，返回可回放的记录。"""

    return save_runs([BacktestRunPlan(request=request, spec=spec, result=result)])[0]


def save_runs(plans: Sequence[BacktestRunPlan]) -> tuple[BacktestRunRecord, ...]:
    """把一批回测写进**同一个事务**：要么全部落库，要么一行都不留。

    指标、逐腿交易与逐 bar 曲线在动手写库之前算好：输入自相矛盾时还没有任何一行进入
    数据库。写库阶段整批共用一个事务，最后一条失败会连同前面几条一起回滚，因此「接口
    返回错误但库里多了几条」不会发生。
    """

    if not plans:
        raise ValidationError("回测批次不能为空")
    prepared = [_prepare(plan) for plan in plans]
    with session_scope() as session:
        for item in prepared:
            session.add(item.run_row)
            # 先落运行行：交易与净值两表按 run_id 做外键，父子顺序不能靠数据库碰运气。
            session.flush()
            session.add_all(item.trade_rows)
            session.add_all(item.equity_rows)
    return tuple(item.record for item in prepared)


@dataclass(frozen=True, slots=True)
class _PreparedRun:
    """一份计划算完后的待写行与读回记录：算与写分开，写库阶段只剩 insert。"""

    run_row: BacktestRunRow
    trade_rows: tuple[BacktestTradeRow, ...]
    equity_rows: tuple[BacktestEquityRow, ...]
    record: BacktestRunRecord


def _prepare(plan: BacktestRunPlan) -> _PreparedRun:
    """把一份计划算成三张表的待写行与读回记录；只计算，不碰数据库。"""

    request, spec, result = plan.request, plan.spec, plan.result
    _require_same_run(request, spec, result)
    bar_times = [point.time for point in result.equity_curve]
    exposure = exposure_series(request.targets, bar_times)
    trades = closed_trades(result.fills, request.instruments)
    metrics = compute_metrics(
        equity=[point.equity for point in result.equity_curve],
        initial_capital=result.initial_capital,
        trades=trades,
        annualization_factor=default_annualization_factor(spec.bar),
        risk_free_rate=ZERO,
    )
    portfolio = portfolio_metrics(trades, exposure)
    result_hash = _result_hash(spec)
    run_id = "bt_" + uuid4().hex[:24]
    created_at = datetime.now(UTC).replace(microsecond=0)

    run_row = BacktestRunRow(
        run_id=run_id,
        strategy_instance_id=spec.strategy_instance_id,
        strategy_id=spec.strategy_id,
        strategy_version=spec.strategy_version,
        params_json=_json_text(spec.params),
        bar=spec.bar,
        start_date=spec.start_date,
        end_date=spec.end_date,
        data_source=spec.data_source,
        inst_id=spec.inst_id,
        inst_type=spec.inst_type,
        request_json=_json_text(spec.request),
        data_fingerprint=spec.data_fingerprint,
        execution_model=spec.execution_model,
        costs_json=_json_text(spec.costs.as_dict()),
        metrics_json=_metrics_json(metrics),
        portfolio_json=_portfolio_json(portfolio),
        funding_total=quantize_money(result.funding_total),
        result_hash=result_hash,
        created_at=_epoch(created_at),
    )
    trade_rows = tuple(
        BacktestTradeRow(
            trade_id=f"{run_id}:{index:06d}",
            run_id=run_id,
            product_key=trade.product_key,
            inst_id=trade.inst_id,
            inst_type=trade.inst_type,
            side=trade.side,
            qty=quantize_money(trade.qty),
            entry_time=_epoch(trade.entry_time),
            entry_price=trade.entry_price,
            exit_time=_epoch(trade.exit_time),
            exit_price=trade.exit_price,
            fee=trade.fee,
            slippage=trade.slippage,
            pnl=trade.pnl,
            reason=trade.reason,
        )
        for index, trade in enumerate(trades)
    )
    equity_rows = tuple(
        BacktestEquityRow(
            run_id=run_id,
            time=_epoch(point.time),
            equity=point.equity,
            net_exposure=exposure[index].net_exposure,
        )
        for index, point in enumerate(result.equity_curve)
    )
    record = BacktestRunRecord(
        run_id=run_id,
        strategy_instance_id=spec.strategy_instance_id,
        strategy_id=spec.strategy_id,
        strategy_version=spec.strategy_version,
        params=MappingProxyType(dict(spec.params)),
        bar=spec.bar,
        start_date=spec.start_date,
        end_date=spec.end_date,
        data_source=spec.data_source,
        inst_id=spec.inst_id,
        inst_type=spec.inst_type,
        request=MappingProxyType(dict(spec.request)),
        data_fingerprint=spec.data_fingerprint,
        execution_model=spec.execution_model,
        costs=MappingProxyType(dict(spec.costs.as_dict())),
        metrics=MappingProxyType(dict(metrics)),
        portfolio=portfolio,
        funding_total=quantize_money(result.funding_total),
        result_hash=result_hash,
        created_at=created_at,
        trades=trades,
        equity=tuple(result.equity_curve),
        exposure=exposure,
    )
    return _PreparedRun(
        run_row=run_row,
        trade_rows=trade_rows,
        equity_rows=equity_rows,
        record=record,
    )


def get_run(run_id: str) -> BacktestRunRecord | None:
    """按运行标识取回一次回测的三层记录；不存在返回 `None`。

    域层用 `None` 表示「没有这次回测」，由 API 层翻译成 404——与机会发现域同一口径。
    """

    with session_scope() as session:
        row = session.get(BacktestRunRow, run_id)
        if row is None:
            return None
        trade_rows = list(
            session.scalars(
                select(BacktestTradeRow)
                .where(BacktestTradeRow.run_id == run_id)
                .order_by(BacktestTradeRow.trade_id)
            )
        )
        equity_rows = list(
            session.scalars(
                select(BacktestEquityRow)
                .where(BacktestEquityRow.run_id == run_id)
                .order_by(BacktestEquityRow.time)
            )
        )
    return _record(row, trade_rows, equity_rows)


@dataclass(frozen=True, slots=True)
class BacktestRunHeader:
    """列表与排行榜读的一行：身份、汇总与组合级指标。

    逐笔交易、资金曲线与完整请求只有详情接口需要，列表不读它们：一页 50 条若都带上
    逐 bar 曲线，一次翻阅就要读出几十万行。
    """

    run_id: str
    strategy_instance_id: str
    strategy_id: str
    strategy_version: str
    params: Mapping[str, Any]
    inst_id: str
    inst_type: str
    bar: str
    start_date: date
    end_date: date
    data_source: str
    execution_model: str
    metrics: Mapping[str, Decimal]
    portfolio: PortfolioMetrics
    funding_total: Decimal
    created_at: datetime


def list_runs(
    data_source: str,
    *,
    limit: int = 50,
) -> tuple[tuple[BacktestRunHeader, ...], int]:
    """按数据源列出回测记录（新到旧），返回（本页，总条数）。

    `data_source` 必填：代理数据与 OKX 实盘标的不可比，跨源聚合会给出错误的排序。
    `limit` 由调用方保证为正（API 层用 `Query(ge=1)` 收口）。没有记录时返回空列表，
    不报错——「还没跑过」与「库坏了」是两件事。
    """

    if not isinstance(data_source, str) or not data_source.strip():
        raise ValidationError("回测列表的 data_source 不能为空")
    condition = BacktestRunRow.data_source == data_source
    statement = (
        select(BacktestRunRow)
        .where(condition)
        .order_by(BacktestRunRow.created_at.desc(), BacktestRunRow.run_id)
        .limit(limit)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
        total = session.scalar(select(func.count()).select_from(BacktestRunRow).where(condition))
    return tuple(_header(row) for row in rows), total or 0


def latest_run(*, created_since: datetime | None = None) -> BacktestRunHeader | None:
    """取最近创建的一次回测；可按创建时刻设下限。

    这里只按创建时刻取一条，不比较不同数据源的指标，也不在多个标的之间求和：
    一次回测只代表一个标的，把多条运行拼成「组合收益」会造出一个没有对应事实的数字。
    """

    if created_since is not None and created_since.tzinfo is None:
        raise ValidationError("最近回测的创建时间下限必须带时区")
    statement = select(BacktestRunRow)
    if created_since is not None:
        statement = statement.where(BacktestRunRow.created_at >= _epoch(created_since))
    statement = statement.order_by(
        BacktestRunRow.created_at.desc(), BacktestRunRow.run_id.desc()
    ).limit(1)
    with session_scope() as session:
        row = session.scalars(statement).first()
    return None if row is None else _header(row)


def list_instrument_runs(
    inst_id: str,
    *,
    created_since: datetime | None = None,
    limit: int = 20,
) -> tuple[BacktestRunHeader, ...]:
    """按标的名取最近的运行记录（新到旧），可限制创建时间下限。

    这里不按数据源过滤：详情页只回答「这个标的有哪些关联回测」，不在跨源结果之间
    排序或比较。每行仍带 `data_source`，界面能区分代理行情与 OKX 行情。
    """

    symbol = inst_id.strip()
    if not symbol:
        raise ValidationError("关联回测的标的不能为空")
    if limit < 1:
        raise ValidationError(f"关联回测的条数必须是正整数:{limit}")
    if created_since is not None and created_since.tzinfo is None:
        raise ValidationError("关联回测的创建时间下限必须带时区")

    statement = select(BacktestRunRow).where(BacktestRunRow.inst_id == symbol)
    if created_since is not None:
        statement = statement.where(BacktestRunRow.created_at >= _epoch(created_since))
    statement = statement.order_by(
        BacktestRunRow.created_at.desc(), BacktestRunRow.run_id.desc()
    ).limit(limit)
    with session_scope() as session:
        rows = list(session.scalars(statement))
    return tuple(_header(row) for row in rows)


def latest_linked_backtests(
    version_ids: Sequence[str],
    *,
    created_since: datetime | None = None,
) -> dict[str, BacktestRunHeader]:
    """每个策略版本最近一次关联回测；只读 `strategy_linked_backtests` 的正式关联。

    不用策略名称或实例名做模糊匹配：关联由写入方在回测创建成功后登记，一条运行
    可以指向一个确定的版本。`created_since` 用于详情页的「最近一个月」窗口；时间
    下限作用在回测创建时刻上，不按回测区间过滤。
    """

    if not version_ids:
        return {}
    if created_since is not None and created_since.tzinfo is None:
        raise ValidationError("关联回测的创建时间下限必须带时区")
    statement = (
        select(StrategyLinkedBacktestRow.strategy_version_id, BacktestRunRow)
        .join(
            BacktestRunRow,
            BacktestRunRow.run_id == StrategyLinkedBacktestRow.backtest_run_id,
        )
        .where(StrategyLinkedBacktestRow.strategy_version_id.in_(list(version_ids)))
        .order_by(BacktestRunRow.created_at.desc(), BacktestRunRow.run_id.desc())
    )
    if created_since is not None:
        statement = statement.where(BacktestRunRow.created_at >= _epoch(created_since))
    with session_scope() as session:
        rows = session.execute(statement).all()
    latest: dict[str, BacktestRunHeader] = {}
    for version_id, row in rows:
        latest.setdefault(version_id, _header(row))
    return latest


def delete_run(run_id: str) -> bool:
    """删掉一次回测及其逐笔交易与资金曲线；不存在返回 `False`。

    子表按外键 `ON DELETE CASCADE` 一并删除，删除语义只有迁移里那一处。
    """

    with session_scope() as session:
        row = session.get(BacktestRunRow, run_id)
        if row is None:
            return False
        session.delete(row)
    return True


def _require_same_run(
    request: BacktestInput,
    spec: BacktestSpec,
    result: BacktestResult,
) -> None:
    """输入与结果必须描述同一次回测；拼错的对象在这里就失败，而不是写进库里。"""

    if request.execution_model != spec.execution_model or (
        result.execution_model != spec.execution_model
    ):
        raise ValidationError(
            f"执行模型不一致: spec={spec.execution_model} "
            f"request={request.execution_model} result={result.execution_model}"
        )
    if Decimal(spec.initial_capital) != Decimal(result.initial_capital):
        raise ValidationError(
            f"初始资金不一致: spec={spec.initial_capital} result={result.initial_capital}"
        )


def _result_hash(spec: BacktestSpec) -> str:
    """可复现输入的摘要：策略版本、参数、标的、数据区间与指纹、执行模型、数据源、成本与请求。

    `request` 一并纳入：仓位上限、每笔金额、标的集合这些只在请求里出现的输入同样会改变
    结果，摘要必须跟着变，否则「改了仓位上限仍报同一个哈希」会让复现核对失效。
    """

    payload: dict[str, Any] = {
        "strategy_id": spec.strategy_id,
        "strategy_version": spec.strategy_version,
        "params": spec.params,
        "inst_id": spec.inst_id,
        "inst_type": spec.inst_type,
        "bar": spec.bar,
        "start_date": spec.start_date.isoformat(),
        "end_date": spec.end_date.isoformat(),
        "data_source": spec.data_source,
        "data_fingerprint": spec.data_fingerprint,
        "execution_model": spec.execution_model,
        "initial_capital": decimal_text(spec.initial_capital),
        "costs": spec.costs.as_dict(),
        "request": dict(spec.request),
    }
    return _sha256(payload)


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _metrics_json(metrics: Mapping[str, Decimal]) -> str:
    return _json_text({name: decimal_text(value) for name, value in metrics.items()})


def _portfolio_json(portfolio: PortfolioMetrics) -> str:
    return _json_text(
        {
            "net_exposure": decimal_text(portfolio.net_exposure),
            "leg_win_rate": {
                key: decimal_text(value) for key, value in portfolio.leg_win_rate.items()
            },
            "long_pnl": decimal_text(portfolio.long_pnl),
            "short_pnl": decimal_text(portfolio.short_pnl),
        }
    )


def _record(
    row: BacktestRunRow,
    trade_rows: Sequence[BacktestTradeRow],
    equity_rows: Sequence[BacktestEquityRow],
) -> BacktestRunRecord:
    """把三张表的行拼回一个记录；JSON 文本在这里还原成映射与定点数。"""

    metrics = {name: Decimal(value) for name, value in json.loads(row.metrics_json).items()}
    portfolio_raw = json.loads(row.portfolio_json)
    portfolio = PortfolioMetrics(
        net_exposure=Decimal(portfolio_raw["net_exposure"]),
        leg_win_rate=MappingProxyType(
            {key: Decimal(value) for key, value in portfolio_raw["leg_win_rate"].items()}
        ),
        long_pnl=Decimal(portfolio_raw["long_pnl"]),
        short_pnl=Decimal(portfolio_raw["short_pnl"]),
    )
    return BacktestRunRecord(
        run_id=row.run_id,
        strategy_instance_id=row.strategy_instance_id,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        params=MappingProxyType(json.loads(row.params_json)),
        bar=row.bar,
        start_date=row.start_date,
        end_date=row.end_date,
        data_source=row.data_source,
        inst_id=row.inst_id,
        inst_type=row.inst_type,
        request=MappingProxyType(json.loads(row.request_json)),
        data_fingerprint=row.data_fingerprint,
        execution_model=row.execution_model,
        costs=MappingProxyType(json.loads(row.costs_json)),
        metrics=MappingProxyType(dict(metrics)),
        portfolio=portfolio,
        funding_total=Decimal(row.funding_total),
        result_hash=row.result_hash,
        created_at=_from_epoch(row.created_at),
        trades=tuple(
            ClosedTrade(
                product_key=trade.product_key,
                inst_id=trade.inst_id,
                inst_type=trade.inst_type,
                side=trade.side,
                qty=Decimal(trade.qty),
                entry_price=Decimal(trade.entry_price),
                entry_time=_from_epoch(trade.entry_time),
                exit_price=Decimal(trade.exit_price),
                exit_time=_from_epoch(trade.exit_time),
                fee=Decimal(trade.fee),
                slippage=Decimal(trade.slippage),
                pnl=Decimal(trade.pnl),
                reason=trade.reason,
            )
            for trade in trade_rows
        ),
        equity=tuple(
            EquityPoint(time=_from_epoch(point.time), equity=Decimal(point.equity))
            for point in equity_rows
        ),
        exposure=tuple(
            ExposurePoint(time=_from_epoch(point.time), net_exposure=Decimal(point.net_exposure))
            for point in equity_rows
        ),
    )


def _epoch(value: datetime) -> int:
    return int(value.astimezone(UTC).replace(microsecond=0).timestamp())


def _from_epoch(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _header(row: BacktestRunRow) -> BacktestRunHeader:
    """运行行 → 列表项：指标与组合汇总从 JSON 文本还原成定点数。"""

    portfolio_raw = json.loads(row.portfolio_json)
    return BacktestRunHeader(
        run_id=row.run_id,
        strategy_instance_id=row.strategy_instance_id,
        strategy_id=row.strategy_id,
        strategy_version=row.strategy_version,
        params=MappingProxyType(json.loads(row.params_json)),
        inst_id=row.inst_id,
        inst_type=row.inst_type,
        bar=row.bar,
        start_date=row.start_date,
        end_date=row.end_date,
        data_source=row.data_source,
        execution_model=row.execution_model,
        metrics=MappingProxyType(
            {name: Decimal(value) for name, value in json.loads(row.metrics_json).items()}
        ),
        portfolio=PortfolioMetrics(
            net_exposure=Decimal(portfolio_raw["net_exposure"]),
            leg_win_rate=MappingProxyType(
                {key: Decimal(value) for key, value in portfolio_raw["leg_win_rate"].items()}
            ),
            long_pnl=Decimal(portfolio_raw["long_pnl"]),
            short_pnl=Decimal(portfolio_raw["short_pnl"]),
        ),
        funding_total=Decimal(row.funding_total),
        created_at=_from_epoch(row.created_at),
    )
