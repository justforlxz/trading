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

from sqlalchemy import select

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

__all__ = [
    "BacktestRunRecord",
    "BacktestSpec",
    "data_fingerprint",
    "get_run",
    "save_run",
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


@dataclass(frozen=True, slots=True)
class BacktestRunRecord:
    """一次已落库的回测：身份、汇总、逐腿交易与逐 bar 曲线。

    `equity` 与 `exposure` 一一对应（同一根 bar 的净值和该 bar 在用的净敞口）。
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


def save_run(
    request: BacktestInput,
    spec: BacktestSpec,
    result: BacktestResult,
) -> BacktestRunRecord:
    """把一次已经跑完的回测算成指标并落库，返回可回放的记录。

    `request` 提供目标组合序列（净敞口序列的来源）与标的静态信息（数量乘数与类别），
    `result` 提供净值曲线、逐腿成交与资金费合计。三者描述的是同一次回测：执行模型与初始
    资金必须一致，不一致说明调用方把两次回测的输入与结果拼在了一起，直接判错而不是写入
    一行自相矛盾的记录。
    """

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

    with session_scope() as session:
        session.add(
            BacktestRunRow(
                run_id=run_id,
                strategy_instance_id=spec.strategy_instance_id,
                strategy_id=spec.strategy_id,
                strategy_version=spec.strategy_version,
                params_json=_json_text(spec.params),
                bar=spec.bar,
                start_date=spec.start_date,
                end_date=spec.end_date,
                data_source=spec.data_source,
                data_fingerprint=spec.data_fingerprint,
                execution_model=spec.execution_model,
                costs_json=_json_text(spec.costs.as_dict()),
                metrics_json=_metrics_json(metrics),
                portfolio_json=_portfolio_json(portfolio),
                funding_total=quantize_money(result.funding_total),
                result_hash=result_hash,
                created_at=_epoch(created_at),
            )
        )
        # 先落运行行：交易与净值两表按 run_id 做外键，父子顺序不能靠数据库碰运气。
        session.flush()
        session.add_all(
            [
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
            ]
        )
        session.add_all(
            [
                BacktestEquityRow(
                    run_id=run_id,
                    time=_epoch(point.time),
                    equity=point.equity,
                    net_exposure=exposure[index].net_exposure,
                )
                for index, point in enumerate(result.equity_curve)
            ]
        )

    return BacktestRunRecord(
        run_id=run_id,
        strategy_instance_id=spec.strategy_instance_id,
        strategy_id=spec.strategy_id,
        strategy_version=spec.strategy_version,
        params=MappingProxyType(dict(spec.params)),
        bar=spec.bar,
        start_date=spec.start_date,
        end_date=spec.end_date,
        data_source=spec.data_source,
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
    """可复现输入的摘要：策略版本、参数、数据区间、数据指纹、执行模型、数据源与成本。"""

    payload: dict[str, Any] = {
        "strategy_id": spec.strategy_id,
        "strategy_version": spec.strategy_version,
        "params": spec.params,
        "bar": spec.bar,
        "start_date": spec.start_date.isoformat(),
        "end_date": spec.end_date.isoformat(),
        "data_source": spec.data_source,
        "data_fingerprint": spec.data_fingerprint,
        "execution_model": spec.execution_model,
        "initial_capital": decimal_text(spec.initial_capital),
        "costs": spec.costs.as_dict(),
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
