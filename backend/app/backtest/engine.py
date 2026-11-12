"""回测引擎：组合级 bar 循环、逐腿成交与净值曲线。

引擎跑的是**目标组合**，不是单标的单一持仓：同一账户里可以同时持有多头与空头腿，
按组合级资金与净敞口结算，成本按腿计。所有计算都是纯函数，输入相同则输出逐字段相同。

## 时间口径

`TargetPortfolio.as_of` 是目标组合所依据的那根 K 线的开盘时刻；它只在**下一根** K 线
上成交。因此 t 时点的成交只依赖 t-1 及更早的目标组合与行情，把 t 之后的行情整段
截断重跑，t 时点的信号与成交不会变。

## 每根 bar 上的结算顺序

顺序固定，不随调用方变化：

1. 结算资金费、保证金与强平（调用注入的结算入口；未注入时这一步恒为 0）；
2. 撮合本 bar 触发的成交：先按强平价平掉被强平的腿、再判退出价位，最后按目标组合调仓；
3. 记录本 bar 收盘时的净值与保证金占用。

顺序反过来，同一根 bar 的结果就会依赖实现细节：调仓数量按结算后的可用资金换算，
先调仓再结算会得到另一个数量。

### 退出与调仓的关系

同一根 bar 上，某条腿按价位退出后**不再按目标组合重建**，重建只能等下一根 bar 的
新目标。原因是两种做法都不成立的情况只有一种：退出把持仓清掉之后，`plan_orders` 会
看到空仓并把这条腿又建回来，成交价取本 bar 的开盘价或收盘价——止损平掉敞口后立刻
按原权重买回，止损等于没有生效，净值会因为「止损价与重建价之差 + 多付一次手续费」
系统性偏低。跳过当根重建把口径说死：价位出场即结束这条腿，策略想继续持有就要在
下一根 bar 重新给出目标。被强平的腿按同一口径处理：它在这根 bar 上就是被交易所平掉
了，不会因为目标组合还指着它就原地重建。

`margin_curve` 记的是结算步看到的保证金占用：占用额在调仓之前算，强平与调仓都发生在
它之后。一根 bar 上刚建的仓位在下一次结算前不占用保证金，因此新仓位的占用额落在下一
根 bar 上——这条口径与「结算先于调仓」的顺序出自同一处，不另开口径。

## 分工

本模块不算指标、不读交易所、不写数据库。资金费、保证金与强平的公式在 T4.5 的纯函数与
`settlement.AccountSettlement` 里，通过 `settle` 参数注入；本节点只保证调用时刻、账本
记账与强平后不再重建。调用方显式传 `settle=None` 时不结资金费、不占保证金、不判强平。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtest.costs import CostModel, decimal_text
from app.backtest.errors import BarSeriesError
from app.backtest.simulation import (
    ExecutionResult,
    FundingReport,
    LegCost,
    LegExit,
    LegFill,
    LegLiquidation,
    LegOrder,
    LegPosition,
    Settlement,
    SettlementOutcome,
    execute_orders,
    instrument_for,
    plan_orders,
    require_positive,
    resolve_exit,
)
from app.core import Bar, InstrumentRef, InvariantViolation, ValidationError
from app.strategy import TargetPortfolio

__all__ = [
    "BacktestInput",
    "BacktestResult",
    "EquityPoint",
    "MarginPoint",
    "run_backtest",
]

#: 执行模型：`next_open` 在下一根 K 线开盘成交，`next_close` 在其收盘成交。
NEXT_OPEN = "next_open"
NEXT_CLOSE = "next_close"
EXECUTION_MODELS = (NEXT_OPEN, NEXT_CLOSE)

#: 强平的成交原因；与止盈止损区分开，结果里能直接读出「这条腿是被强平掉的」。
LIQUIDATION = "liquidation"

ZERO = Decimal(0)

#: 结算入口：接收本 bar 的结算状态，返回现金、保证金占用与强平事实。
SettleFn = Callable[[Settlement], SettlementOutcome]


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """一个 bar 收盘时的组合净值点。"""

    time: datetime
    equity: Decimal


@dataclass(frozen=True, slots=True)
class MarginPoint:
    """一个 bar 收盘时的保证金占用与可用资金。

    `equity` 与同一时刻的 `EquityPoint.equity` 相同，一起记下来才能让
    「已占用保证金 + 可用资金 == 权益」直接在单条记录上核对。

    `margin_used` 是这根 bar 的**结算步**认定的占用额：它在强平与调仓之前算，因此强平
    那根 bar 上仍有值——那正是这条腿占着保证金、随后被强平的那一刻。

    保证金不放在 `EquityPoint` 上：`EquityPoint` 同时用来读回落库的净值曲线，而
    `backtest_equity` 没有保证金列；共用同一个类型会让读回的历史记录把占用额显示成 0。
    """

    time: datetime
    equity: Decimal
    margin_used: Decimal

    @property
    def available(self) -> Decimal:
        """可用资金 = 权益 − 已占用保证金。"""

        return self.equity - self.margin_used


@dataclass(frozen=True, slots=True)
class BacktestInput:
    """一次回测的全部输入。

    `bars` 与 `instruments` 都按 `product_key` 索引，与 `TargetPortfolio` 的腿使用
    同一套键，因此不必在引擎内部再把产品键换成标的串。`instruments` 选哪一个形态
    （现货还是永续）由调用方决定，引擎只按它的类别规则换算数量与名义金额。
    """

    bars: Mapping[str, Sequence[Bar]]
    instruments: Mapping[str, InstrumentRef]
    targets: Sequence[TargetPortfolio]
    initial_capital: Decimal
    execution_model: str
    costs: CostModel
    settle: SettleFn | None
    exits: Mapping[str, LegExit] | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """一次回测的结果：净值曲线、逐腿成交、按腿成本与可复现标识。

    `result_hash` 是上面这些字段的规范化摘要；同样的输入跑两次得到同一个值。
    `net_exposure` 取最后一次生效的目标组合的净敞口（多头权重之和减空头权重之和）。

    `margin_curve` 与 `equity_curve` 逐 bar 对齐：一行是同一根 bar 的权益与保证金占用。
    `liquidations` 是本段行情里真的发生的强平（哪一腿、哪根 bar、哪一价位）；
    `funding_report` 是资金费账本的可读摘要（覆盖率与三个缺口计数器），没有资金费账本
    时为 `None`——它让「上游费率全缺失」与「费率确实是 0」不再都只是
    `funding_total=0`。
    """

    execution_model: str
    initial_capital: Decimal
    equity_curve: tuple[EquityPoint, ...]
    fills: tuple[LegFill, ...]
    costs: tuple[LegCost, ...]
    funding_total: Decimal
    net_exposure: Decimal
    result_hash: str
    margin_curve: tuple[MarginPoint, ...]
    liquidations: tuple[LegLiquidation, ...]
    funding_report: FundingReport | None


@dataclass(slots=True)
class _Book:
    """循环期间的账户状态。可变的只有它，外部拿到的是冻结的 `BacktestResult`。

    `equity` 与 `apply` 都写在类里：净值公式只有一处，成交怎么并入账户也只有一处，
    循环本身只负责决定「这一刻该发生什么」。
    """

    capital: Decimal
    positions: dict[str, LegPosition] = field(default_factory=dict)
    realized: Decimal = ZERO
    fees: Decimal = ZERO
    funding: Decimal = ZERO
    fills: list[LegFill] = field(default_factory=list)
    cost_book: dict[str, list[Decimal]] = field(default_factory=dict)

    def equity(self, prices: Mapping[str, Decimal]) -> Decimal:
        """组合净值 = 初始资金 + 已实现盈亏 + 资金费现金流 - 手续费 + 浮动盈亏。"""

        value = self.capital + self.realized + self.funding - self.fees
        for position in self.positions.values():
            price = prices.get(position.product_key)
            if price is None:
                raise BarSeriesError(f"标的 {position.product_key} 在该时刻没有可用价格")
            value += position.unrealized(price)
        return value

    def apply(self, outcome: ExecutionResult) -> None:
        self.positions.clear()
        self.positions.update(outcome.positions)
        self.fills.extend(outcome.fills)
        self.realized += outcome.realized
        self.fees += outcome.fees
        for fill in outcome.fills:
            bucket = self.cost_book.setdefault(fill.product_key, [ZERO, ZERO])
            bucket[0] += fill.fee
            bucket[1] += fill.slippage


def run_backtest(request: BacktestInput) -> BacktestResult:
    """按 `BacktestInput` 跑完一段组合级 bar 循环。"""

    capital = require_positive(request.initial_capital, "initial_capital")
    if request.execution_model not in EXECUTION_MODELS:
        raise ValidationError(
            f"未知执行模型 {request.execution_model!r}; 可选 {list(EXECUTION_MODELS)}"
        )
    _begin_run(request.settle)

    series = _series(request.bars)
    timeline = sorted({moment for rows in series.values() for moment in rows})
    if not timeline:
        raise BarSeriesError("行情为空")
    due_at = _targets_by_time(request.targets, timeline)
    levels = dict(request.exits or {})

    book = _Book(capital=capital)
    last_price: dict[str, Decimal] = {}
    curve: list[EquityPoint] = []
    margins: list[MarginPoint] = []
    liquidations: list[LegLiquidation] = []
    funding_report: FundingReport | None = None
    net_exposure = ZERO

    for index, moment in enumerate(timeline):
        here = {key: rows[moment] for key, rows in series.items() if moment in rows}
        for key, candle in here.items():
            last_price[key] = candle.close
        executed = _reference_prices(here, request.execution_model)
        marked = {**last_price, **executed}

        # ① 结算资金费、保证金与强平：现金流先落地，后面的调仓按结算后的资金换算数量。
        #    被强平的腿在结算步就地平掉，并与价位退出一样不参与本 bar 的重建。
        occupied = ZERO
        liquidated: set[str] = set()
        if request.settle is not None and book.positions:
            outcome = _settle(request.settle, moment, book, marked, here)
            book.funding += outcome.cash
            occupied = outcome.margin_used
            if outcome.funding_report is not None:
                funding_report = outcome.funding_report
            liquidations.extend(outcome.liquidated)
            liquidated = _liquidate(request, book, outcome.liquidated, moment)

        # ② 撮合本 bar 触发的成交：先看退出价位，再按目标组合调仓。
        exited = liquidated | _exit_by_level(request, book, here, levels, executed, moment)
        target = due_at.get(timeline[index - 1]) if index > 0 else None
        if target is not None:
            _follow_target(request, book, target, executed, marked, exited, moment)
            net_exposure = target.net_exposure

        # ③ 记录净值与保证金占用：净值按本 bar 收盘价计价。
        equity = book.equity(last_price)
        curve.append(EquityPoint(time=moment, equity=equity))
        margins.append(MarginPoint(time=moment, equity=equity, margin_used=occupied))

    return _build_result(
        request,
        book,
        tuple(curve),
        tuple(margins),
        tuple(liquidations),
        funding_report,
        net_exposure,
    )


def _begin_run(settle: SettleFn | None) -> None:
    """进入 bar 循环前建立本次回测的显式边界：有累计状态的结算入口在此重置。

    不按「结算时刻是否回退」推断复用：第二次回测的时间窗可以整体更晚，那样推断不出来。
    结算入口实现 `begin_run()` 时调用它（`AccountSettlement` 转发给资金费账本）；没有
    累计状态的普通回调不需要实现本方法。
    """

    begin = getattr(settle, "begin_run", None)
    if callable(begin):
        begin()


def _reference_prices(here: Mapping[str, Bar], execution_model: str) -> dict[str, Decimal]:
    """本 bar 的执行参考价：`next_open` 取开盘价，`next_close` 取收盘价。"""

    if execution_model == NEXT_OPEN:
        return {key: candle.open for key, candle in here.items()}
    return {key: candle.close for key, candle in here.items()}


def _settle(
    settle: SettleFn,
    moment: datetime,
    book: _Book,
    prices: Mapping[str, Decimal],
    bars: Mapping[str, Bar],
) -> SettlementOutcome:
    """调用注入的结算入口，并确认它交回的确实是结算产出。

    结算入口必须返回 `SettlementOutcome`：它以前只回传一个现金数字，保证金与强平没有
    通道；这里把「只回传现金」判成错误，而不是让 `Decimal` 走进账本再在别处炸开。
    """

    outcome = settle(
        Settlement(
            moment=moment,
            equity=book.equity(prices),
            positions=tuple(book.positions.values()),
            prices=prices,
            bars=bars,
        )
    )
    if not isinstance(outcome, SettlementOutcome):
        raise ValidationError(f"结算入口必须返回 SettlementOutcome, 实际 {type(outcome).__name__}")
    return outcome


def _liquidate(
    request: BacktestInput,
    book: _Book,
    records: Sequence[LegLiquidation],
    moment: datetime,
) -> set[str]:
    """把结算入口报告的被强平腿按强平价平掉，返回本 bar 已退出的产品键。

    成交走与止盈止损同一条路径（`execute_orders`）：手续费与滑点照计，已实现盈亏并入
    账户；强平价本身作为成交参考价，跳空时不模拟更差的成交价。
    """

    if not records:
        return set()

    orders: list[LegOrder] = []
    prices: dict[str, Decimal] = {}
    for record in records:
        position = book.positions.get(record.product_key)
        if position is None:
            raise InvariantViolation(
                f"结算入口报告了不存在的腿 {record.product_key} 的强平, 该腿当前没有持仓"
            )
        orders.append(
            LegOrder(
                product_key=record.product_key,
                inst_id=instrument_for(request.instruments, record.product_key).inst_id,
                side=position.side,
                qty=position.qty,
                opening=False,
                multiplier=position.multiplier,
                reason=LIQUIDATION,
            )
        )
        prices[record.product_key] = record.price

    book.apply(
        execute_orders(
            orders,
            book.positions,
            prices=prices,
            costs=request.costs,
            bar_open_time=moment,
        )
    )
    return {order.product_key for order in orders}


def _exit_by_level(
    request: BacktestInput,
    book: _Book,
    here: Mapping[str, Bar],
    levels: Mapping[str, LegExit],
    executed: Mapping[str, Decimal],
    moment: datetime,
) -> set[str]:
    """按价位退出，返回本 bar 已退出的标的；它们不再参与当根 bar 的调仓。"""

    orders: list[LegOrder] = []
    prices = dict(executed)
    for key, position in book.positions.items():
        candle = here.get(key)
        level = levels.get(key)
        if candle is None or level is None:
            continue
        hit = resolve_exit(position, level, high=candle.high, low=candle.low)
        if hit is None:
            continue
        reason, price = hit
        orders.append(
            LegOrder(
                product_key=key,
                inst_id=instrument_for(request.instruments, key).inst_id,
                side=position.side,
                qty=position.qty,
                opening=False,
                multiplier=position.multiplier,
                reason=reason,
            )
        )
        prices[key] = price
    if not orders:
        return set()

    book.apply(
        execute_orders(
            orders,
            book.positions,
            prices=prices,
            costs=request.costs,
            bar_open_time=moment,
        )
    )
    return {order.product_key for order in orders}


def _follow_target(
    request: BacktestInput,
    book: _Book,
    target: TargetPortfolio,
    executed: Mapping[str, Decimal],
    marked: Mapping[str, Decimal],
    exited: set[str],
    moment: datetime,
) -> None:
    """按目标组合调仓；本 bar 已按价位退出的标的跳过，等下一根 bar 的新目标重建。"""

    available = book.equity(marked)
    orders = tuple(
        order
        for order in plan_orders(target, book.positions, request.instruments, executed, available)
        if order.product_key not in exited
    )
    if not orders:
        return

    book.apply(
        execute_orders(
            orders,
            book.positions,
            prices=executed,
            costs=request.costs,
            bar_open_time=moment,
        )
    )


def _build_result(
    request: BacktestInput,
    book: _Book,
    curve: tuple[EquityPoint, ...],
    margins: tuple[MarginPoint, ...],
    liquidations: tuple[LegLiquidation, ...],
    funding_report: FundingReport | None,
    net_exposure: Decimal,
) -> BacktestResult:
    costs = tuple(
        LegCost(
            product_key=key,
            inst_id=instrument_for(request.instruments, key).inst_id,
            fee=values[0],
            slippage=values[1],
        )
        for key, values in sorted(book.cost_book.items())
    )
    fills = tuple(book.fills)
    return BacktestResult(
        execution_model=request.execution_model,
        initial_capital=book.capital,
        equity_curve=curve,
        fills=fills,
        costs=costs,
        funding_total=book.funding,
        net_exposure=net_exposure,
        result_hash=_result_hash(
            execution_model=request.execution_model,
            initial_capital=book.capital,
            curve=curve,
            fills=fills,
            costs=costs,
            funding_total=book.funding,
            margins=margins,
            liquidations=liquidations,
            funding_report=funding_report,
            net_exposure=net_exposure,
        ),
        margin_curve=margins,
        liquidations=liquidations,
        funding_report=funding_report,
    )


def _series(bars: Mapping[str, Sequence[Bar]]) -> dict[str, dict[datetime, Bar]]:
    """把行情整理成「产品键 → 时刻 → K 线」，并拒绝重复与乱序的时刻。

    重复或倒序的行情会让同一个 bar 被处理两次，净值曲线随之失真；这类输入只能由
    调用方修正，本模块不排序掩盖，也不丢数据。
    """

    series: dict[str, dict[datetime, Bar]] = {}
    for key, rows in bars.items():
        if not key.strip():
            raise BarSeriesError("行情的产品键不能为空")
        ordered: dict[datetime, Bar] = {}
        previous: datetime | None = None
        for candle in rows:
            if previous is not None and candle.open_time <= previous:
                raise BarSeriesError(
                    f"标的 {key} 的 K 线必须按开盘时刻严格递增:"
                    f"{previous.isoformat()} 之后出现 {candle.open_time.isoformat()}"
                )
            ordered[candle.open_time] = candle
            previous = candle.open_time
        series[key] = ordered
    return series


def _targets_by_time(
    targets: Sequence[TargetPortfolio], timeline: Sequence[datetime]
) -> dict[datetime, TargetPortfolio]:
    """按 `as_of` 索引目标组合；时刻不在行情时间轴上、或同一时刻给两份都判错。"""

    known = set(timeline)
    indexed: dict[datetime, TargetPortfolio] = {}
    for target in targets:
        if target.as_of not in known:
            raise ValidationError(f"目标组合的时刻 {target.as_of.isoformat()} 不在行情时间轴上")
        if target.as_of in indexed:
            raise ValidationError(
                f"同一时刻 {target.as_of.isoformat()} 给了两份目标组合, 无法确定用哪一份"
            )
        indexed[target.as_of] = target
    return indexed


def _result_hash(
    *,
    execution_model: str,
    initial_capital: Decimal,
    curve: Sequence[EquityPoint],
    fills: Sequence[LegFill],
    costs: Sequence[LegCost],
    funding_total: Decimal,
    margins: Sequence[MarginPoint],
    liquidations: Sequence[LegLiquidation],
    funding_report: FundingReport | None,
    net_exposure: Decimal,
) -> str:
    """把结果字段写成规范化 JSON 再取 sha256；同样的结果必然得到同一个值。

    保证金占用、强平记录与资金费覆盖率也在摘要里：只差档位表或费率覆盖情况的两份输入
    会给出不同的保证金与强平事实，摘要必须跟着变，否则「同参数重跑」看不出这两处差异。
    """

    payload: dict[str, Any] = {
        "execution_model": execution_model,
        "initial_capital": decimal_text(initial_capital),
        "equity_curve": [[point.time.isoformat(), decimal_text(point.equity)] for point in curve],
        "margin_curve": [
            [point.time.isoformat(), decimal_text(point.equity), decimal_text(point.margin_used)]
            for point in margins
        ],
        "liquidations": [
            [
                item.product_key,
                item.side,
                decimal_text(item.price),
                item.bar_open_time.isoformat(),
            ]
            for item in liquidations
        ],
        "funding_report": None
        if funding_report is None
        else [
            decimal_text(funding_report.total),
            funding_report.expected_points,
            funding_report.missing_points,
            funding_report.funding_missing,
            funding_report.rate_zero,
        ],
        "fills": [
            [
                fill.product_key,
                fill.inst_id,
                fill.side,
                decimal_text(fill.qty),
                decimal_text(fill.price),
                fill.bar_open_time.isoformat(),
                decimal_text(fill.fee),
                decimal_text(fill.slippage),
                fill.opening,
                fill.reason,
            ]
            for fill in fills
        ],
        "costs": [
            [cost.product_key, cost.inst_id, decimal_text(cost.fee), decimal_text(cost.slippage)]
            for cost in costs
        ],
        "funding_total": decimal_text(funding_total),
        "net_exposure": decimal_text(net_exposure),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
