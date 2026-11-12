"""两层风控规则与按类别适用声明。

每条规则自己声明适用哪些交易类别, 判定时只问 `trading_rules(inst_type)`：
有保证金的类别才检查杠杆与强平距离, 有资金费的类别才检查资金费率, 没有保证金的
类别才检查现货买入的可用余额。新增类别时注册一张规则表即可, 这里不改判断。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core import ValidationError
from app.instrument import Instrument, TradingRules, trading_categories, trading_rules

__all__ = [
    "Correlation",
    "PositionExposure",
    "RiskContext",
    "RiskDecision",
    "RiskLimits",
    "RuleScope",
    "RuleSpec",
    "RuleViolation",
    "SignalRecord",
    "TradeRequest",
    "applicable_rule_names",
    "evaluate",
    "rule_applicability",
]

ZERO = Decimal(0)
ONE = Decimal(1)
HARD_MAX_LEVERAGE = Decimal("10")
SIDES = frozenset({"buy", "sell"})
ORDER_TYPES = frozenset({"market", "limit"})
POS_SIDES = frozenset({"", "long", "short"})
DIRECTIONS = frozenset({"long", "short"})
LONG = "long"
SHORT = "short"
UNIT_CONTRACT = "contract"


@dataclass(frozen=True, slots=True)
class PositionExposure:
    """一条当前持仓的敞口快照；`notional` 是绝对值, 方向单独存。"""

    instance_id: str
    inst_id: str
    product_key: str
    direction: str
    notional: Decimal

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValidationError("持仓敞口必须给出策略实例")
        if not self.product_key.strip():
            raise ValidationError("持仓敞口必须给出产品键")
        if self.direction not in DIRECTIONS:
            raise ValidationError(f"持仓方向必须是 long / short, 实际 {self.direction!r}")
        if not isinstance(self.notional, Decimal) or not self.notional.is_finite():
            raise ValidationError(f"持仓名义价值必须是有限 Decimal, 实际 {self.notional!r}")
        if self.notional < ZERO:
            raise ValidationError(f"持仓名义价值不能为负, 实际 {self.notional}")

    @property
    def signed_notional(self) -> Decimal:
        return self.notional if self.direction == LONG else -self.notional


@dataclass(frozen=True, slots=True)
class Correlation:
    """两个产品之间的相关系数；用于相关性风险汇总。"""

    product_a: str
    product_b: str
    coefficient: Decimal

    def __post_init__(self) -> None:
        if not self.product_a.strip() or not self.product_b.strip():
            raise ValidationError("相关系数必须给出两个产品键")
        if self.product_a == self.product_b:
            raise ValidationError("相关系数不能比较同一个产品")
        if not isinstance(self.coefficient, Decimal) or not self.coefficient.is_finite():
            raise ValidationError("相关系数必须是有限 Decimal")
        if not -ONE <= self.coefficient <= ONE:
            raise ValidationError(f"相关系数必须在 -1..1 之间, 实际 {self.coefficient}")


@dataclass(frozen=True, slots=True)
class SignalRecord:
    """近期已经产生过的信号, 用于重复信号防护。"""

    instance_id: str
    inst_id: str
    side: str
    at: datetime

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValidationError(f"信号方向必须是 {sorted(SIDES)}, 实际 {self.side!r}")
        if self.at.tzinfo is None:
            raise ValidationError("信号时刻必须带时区")


@dataclass(frozen=True, slots=True)
class RiskContext:
    """一次风控判定需要的组合事实。

    这些值由调用方从组合账本、行情与账户快照装配；规则本身不读库, 也不自己
    推导组合权益。`available_balance` 只对没有保证金的类别有意义。
    """

    equity: Decimal
    strategy_equity: Decimal | None = None
    positions: tuple[PositionExposure, ...] = ()
    recent_signals: tuple[SignalRecord, ...] = ()
    correlations: tuple[Correlation, ...] = ()
    drawdown: Decimal = ZERO
    available_balance: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.equity, Decimal) or not self.equity.is_finite():
            raise ValidationError("组合权益必须是有限 Decimal")
        if self.equity < ZERO:
            raise ValidationError(f"组合权益不能为负, 实际 {self.equity}")
        if self.strategy_equity is not None:
            if (
                not isinstance(self.strategy_equity, Decimal)
                or not self.strategy_equity.is_finite()
            ):
                raise ValidationError("策略权益必须是有限 Decimal")
            if self.strategy_equity < ZERO:
                raise ValidationError(f"策略权益不能为负, 实际 {self.strategy_equity}")
        if not isinstance(self.drawdown, Decimal) or not self.drawdown.is_finite():
            raise ValidationError("组合回撤必须是有限 Decimal")
        if self.drawdown < ZERO:
            raise ValidationError(f"组合回撤不能为负, 实际 {self.drawdown}")
        if self.available_balance is not None:
            if (
                not isinstance(self.available_balance, Decimal)
                or not self.available_balance.is_finite()
            ):
                raise ValidationError("可用余额必须是有限 Decimal")
            if self.available_balance < ZERO:
                raise ValidationError(f"可用余额不能为负, 实际 {self.available_balance}")


@dataclass(frozen=True, slots=True)
class TradeRequest:
    """待判定的下单请求；不是 `OrderIntent`, 风控通过之后才会构造意图。"""

    instance_id: str
    inst_id: str
    side: str
    order_type: str
    qty: Decimal
    ts: datetime
    price: Decimal | None = None
    mark_price: Decimal | None = None
    leverage: Decimal | None = None
    funding_rate: Decimal | None = None
    liquidation_price: Decimal | None = None
    pos_side: str = ""
    reduce_only: bool = False
    client_order_id: str = ""

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValidationError("下单请求必须给出策略实例")
        if not self.inst_id.strip():
            raise ValidationError("下单请求必须给出标的")
        if self.side not in SIDES:
            raise ValidationError(f"下单方向必须是 {sorted(SIDES)}, 实际 {self.side!r}")
        if self.order_type not in ORDER_TYPES:
            raise ValidationError(f"订单类型必须是 {sorted(ORDER_TYPES)}, 实际 {self.order_type!r}")
        _require_positive_decimal(self.qty, "下单数量")
        if self.order_type == "limit":
            if self.price is None:
                raise ValidationError("限价单必须给出 price")
        elif self.price is not None:
            raise ValidationError("市价单不能给出 price")
        if self.price is not None:
            _require_positive_decimal(self.price, "限价")
        if self.mark_price is not None:
            _require_positive_decimal(self.mark_price, "标记价")
        if self.ts.tzinfo is None:
            raise ValidationError("下单时刻必须带时区")
        if self.pos_side not in POS_SIDES:
            raise ValidationError(f"持仓方向必须是 {sorted(POS_SIDES)}, 实际 {self.pos_side!r}")
        for name in ("leverage", "funding_rate", "liquidation_price"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValidationError(f"{name} 必须是有限 Decimal, 实际 {value!r}")
        if self.liquidation_price is not None and self.liquidation_price <= ZERO:
            raise ValidationError("强平价必须为正")

    @property
    def reference_price(self) -> Decimal:
        """判定名义价值用的价格：限价单取委托价, 市价单取标记价。"""

        price = self.price if self.order_type == "limit" else self.mark_price
        if price is None:
            raise ValidationError("市价单需要标记价才能判定名义价值")
        return price


@dataclass(frozen=True, slots=True)
class RuleViolation:
    """一条触发记录；`rule` 与 `RiskBlocked.rule` 同口径。"""

    rule: str
    detail: str


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """纯判定结果：通过时也不构造订单, 订单只在服务层通过后构造。"""

    allowed: bool
    checked_rules: tuple[str, ...]
    violations: tuple[RuleViolation, ...]


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """风控阈值。所有比例为占组合权益的比率, 不是百分数。

    `max_leverage` 是硬上限, 不接受高于 10 的配置（decisions.md L1）。
    """

    max_order_ratio: Decimal = Decimal("0.20")
    max_instrument_weight: Decimal = Decimal("0.30")
    max_positions: int = 10
    duplicate_signal_window_seconds: int = 300
    max_gross_exposure: Decimal = Decimal("2.00")
    max_abs_net_exposure: Decimal = Decimal("1.00")
    max_concentration: Decimal = Decimal("0.40")
    max_correlated_weight: Decimal = Decimal("0.60")
    correlation_threshold: Decimal = Decimal("0.80")
    max_strategies_per_product: int = 2
    max_drawdown: Decimal = Decimal("0.20")
    max_leverage: Decimal = HARD_MAX_LEVERAGE
    default_leverage: Decimal = Decimal("3")
    max_funding_rate: Decimal = Decimal("0.01")
    min_liquidation_distance: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        ratio_fields = (
            "max_order_ratio",
            "max_instrument_weight",
            "max_gross_exposure",
            "max_abs_net_exposure",
            "max_concentration",
            "max_correlated_weight",
            "max_drawdown",
            "min_liquidation_distance",
        )
        for name in ratio_fields:
            _require_non_negative_decimal(getattr(self, name), name)
        _require_non_negative_decimal(self.correlation_threshold, "correlation_threshold")
        if self.correlation_threshold > ONE:
            raise ValidationError("correlation_threshold 不能大于 1")
        _require_non_negative_decimal(self.max_funding_rate, "max_funding_rate")
        _require_positive_decimal(self.max_leverage, "max_leverage")
        if self.max_leverage > HARD_MAX_LEVERAGE:
            raise ValidationError(f"max_leverage 不能高于硬上限 {HARD_MAX_LEVERAGE}")
        _require_positive_decimal(self.default_leverage, "default_leverage")
        if self.default_leverage > self.max_leverage:
            raise ValidationError("default_leverage 不能高于 max_leverage")
        for name in (
            "max_positions",
            "duplicate_signal_window_seconds",
            "max_strategies_per_product",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValidationError(f"{name} 必须是正整数, 实际 {value!r}")


class RuleScope:
    """规则适用的类别特征；不写具体类别名。"""

    ALL = "all"
    MARGIN = "margin"
    FUNDING = "funding"
    NO_MARGIN = "no_margin"

    VALUES = frozenset({ALL, MARGIN, FUNDING, NO_MARGIN})


@dataclass(frozen=True, slots=True)
class _Facts:
    request: TradeRequest
    instrument: Instrument
    context: RiskContext
    limits: RiskLimits
    rules: TradingRules
    notional: Decimal

    @property
    def opening(self) -> bool:
        return not self.request.reduce_only

    @property
    def strategy_equity(self) -> Decimal:
        """策略级限额的分母：有策略预算就用预算，否则退回组合权益。"""

        if self.context.strategy_equity is None:
            return self.context.equity
        return self.context.strategy_equity

    @property
    def direction(self) -> str:
        return LONG if self.request.side == "buy" else SHORT

    @property
    def signed_new(self) -> Decimal:
        return self.notional if self.direction == LONG else -self.notional

    def product_totals(self, *, include_new: bool) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for position in self.context.positions:
            totals[position.product_key] = (
                totals.get(position.product_key, ZERO) + position.signed_notional
            )
        if include_new and self.opening:
            key = self.instrument.product_key
            totals[key] = totals.get(key, ZERO) + self.signed_new
        return totals


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """一条规则：名字、适用特征与判定函数。"""

    name: str
    scope: str
    description: str
    check: Callable[[_Facts], str | None]

    def __post_init__(self) -> None:
        if self.scope not in RuleScope.VALUES:
            raise ValidationError(f"规则 {self.name} 的适用特征未知:{self.scope!r}")


def _scope_applies(scope: str, rules: TradingRules) -> bool:
    if scope == RuleScope.ALL:
        return True
    if scope == RuleScope.MARGIN:
        return rules.has_margin
    if scope == RuleScope.FUNDING:
        return rules.has_funding
    return not rules.has_margin


def _format(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _limit_text(ratio: Decimal, equity: Decimal) -> str:
    return _format(ratio * equity)


# ------------------------------------------------------------------ 策略级


def _order_amount_ratio(facts: _Facts) -> str | None:
    """单笔金额占组合权益的上限；平仓单不增加风险, 直接放过。"""

    if not facts.opening:
        return None
    limit = facts.limits.max_order_ratio * facts.strategy_equity
    if facts.notional > limit:
        return (
            f"单笔金额 {_format(facts.notional)} 超过组合权益的 "
            f"{_format(facts.limits.max_order_ratio)}, 上限 {_format(limit)}"
        )
    return None


def _instrument_weight(facts: _Facts) -> str | None:
    """单个标的的预计净名义价值占权益的上限。"""

    if not facts.opening:
        return None
    current = sum(
        (
            position.signed_notional
            for position in facts.context.positions
            if position.instance_id == facts.request.instance_id
            and position.product_key == facts.instrument.product_key
        ),
        ZERO,
    )
    projected = abs(current + facts.signed_new)
    limit = facts.limits.max_instrument_weight * facts.strategy_equity
    if projected > limit:
        return (
            f"标的 {facts.instrument.product_key} 的权重 {_format(projected)} "
            f"超过上限 {_limit_text(facts.limits.max_instrument_weight, facts.strategy_equity)}"
        )
    return None


def _max_positions(facts: _Facts) -> str | None:
    """同一策略的持仓数量上限；已经持有的标的不重复占位。"""

    if not facts.opening:
        return None
    held = {
        position.product_key
        for position in facts.context.positions
        if position.instance_id == facts.request.instance_id and position.notional > ZERO
    }
    if facts.instrument.product_key in held:
        return None
    if len(held) >= facts.limits.max_positions:
        return (
            f"策略 {facts.request.instance_id} 已持有 {len(held)} 个标的, "
            f"达到上限 {facts.limits.max_positions}"
        )
    return None


def _duplicate_signal(facts: _Facts) -> str | None:
    """同一实例、同一标的、同一方向在时间窗内只允许一次开仓信号。"""

    if not facts.opening:
        return None
    window = timedelta(seconds=facts.limits.duplicate_signal_window_seconds)
    for record in facts.context.recent_signals:
        if (
            record.instance_id == facts.request.instance_id
            and record.inst_id == facts.request.inst_id
            and record.side == facts.request.side
            and timedelta(0) <= facts.request.ts - record.at <= window
        ):
            return (
                f"{record.at.isoformat()} 已产生同方向信号, "
                f"{facts.limits.duplicate_signal_window_seconds} 秒内不重复开仓"
            )
    return None


def _qty_precision(facts: _Facts) -> str | None:
    lot = facts.instrument.lot_size
    if lot is None or lot <= ZERO:
        return f"标的 {facts.instrument.symbol} 缺少有效的 lot_size, 无法确认数量精度"
    if facts.request.qty % lot != ZERO:
        return f"数量 {facts.request.qty} 不是 lot_size {lot} 的整数倍"
    return None


def _price_precision(facts: _Facts) -> str | None:
    if facts.request.order_type != "limit":
        return None
    tick = facts.instrument.tick_size
    if tick is None or tick <= ZERO:
        return f"标的 {facts.instrument.symbol} 缺少有效的 tick_size, 无法确认价格精度"
    assert facts.request.price is not None
    if facts.request.price % tick != ZERO:
        return f"价格 {facts.request.price} 不是 tick_size {tick} 的整数倍"
    return None


# ------------------------------------------------------------------ 全局


def _gross_exposure(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    current = sum((position.notional for position in facts.context.positions), ZERO)
    projected = current + facts.notional
    limit = facts.limits.max_gross_exposure * facts.context.equity
    if projected > limit:
        return f"总敞口 {_format(projected)} 超过上限 {_format(limit)}"
    return None


def _net_exposure(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    current = sum((position.signed_notional for position in facts.context.positions), ZERO)
    projected = abs(current + facts.signed_new)
    limit = facts.limits.max_abs_net_exposure * facts.context.equity
    if projected > limit:
        return f"净敞口绝对值 {_format(projected)} 超过上限 {_format(limit)}"
    return None


def _concentration(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    totals = facts.product_totals(include_new=True)
    largest_product = max(totals, key=lambda key: abs(totals[key]))
    largest = abs(totals[largest_product])
    limit = facts.limits.max_concentration * facts.context.equity
    if largest > limit:
        return f"产品 {largest_product} 的集中度 {_format(largest)} 超过上限 {_format(limit)}"
    return None


def _correlation_risk(facts: _Facts) -> str | None:
    if not facts.opening or not facts.context.correlations:
        return None
    product = facts.instrument.product_key
    totals = facts.product_totals(include_new=True)
    related: set[str] = set()
    for pair in facts.context.correlations:
        if abs(pair.coefficient) < facts.limits.correlation_threshold:
            continue
        if pair.product_a == product:
            related.add(pair.product_b)
        elif pair.product_b == product:
            related.add(pair.product_a)
    exposure = abs(totals.get(product, ZERO)) + sum(
        (abs(totals.get(other, ZERO)) for other in related), ZERO
    )
    limit = facts.limits.max_correlated_weight * facts.context.equity
    if exposure > limit:
        return f"与 {product} 高相关的持仓合计 {_format(exposure)} 超过上限 {_format(limit)}"
    return None


def _multi_strategy_duplicate(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    product = facts.instrument.product_key
    same_direction = {
        position.instance_id
        for position in facts.context.positions
        if position.product_key == product
        and position.direction == facts.direction
        and position.instance_id != facts.request.instance_id
        and position.notional > ZERO
    }
    if len(same_direction) >= facts.limits.max_strategies_per_product:
        return (
            f"已有 {len(same_direction)} 个策略在 {product} 上持有同方向仓位, "
            f"达到上限 {facts.limits.max_strategies_per_product}"
        )
    return None


def _max_drawdown(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    if facts.context.drawdown > facts.limits.max_drawdown:
        return (
            f"组合回撤 {_format(facts.context.drawdown)} 超过上限 "
            f"{_format(facts.limits.max_drawdown)}"
        )
    return None


def _available_balance(facts: _Facts) -> str | None:
    """现货买入受账户可用余额约束；卖出与平仓不检查。"""

    if not facts.opening or facts.request.side != "buy":
        return None
    balance = facts.context.available_balance
    if balance is None:
        return "缺少可用余额, 无法确认现货买入是否超出账户余额"
    if facts.notional > balance:
        return f"买入金额 {_format(facts.notional)} 超过可用余额 {_format(balance)}"
    return None


# ------------------------------------------------------------------ 仅保证金 / 仅资金费


def _leverage(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    leverage = (
        facts.limits.default_leverage if facts.request.leverage is None else facts.request.leverage
    )
    cap = facts.limits.max_leverage
    if facts.instrument.max_lever is not None:
        cap = min(cap, facts.instrument.max_lever)
    if leverage > cap:
        return f"杠杆 {_format(leverage)} 超过上限 {_format(cap)}"
    return None


def _funding_rate(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    if facts.request.funding_rate is None:
        return "缺少当前资金费率, 无法确认是否超过上限"
    rate = abs(facts.request.funding_rate)
    if rate > facts.limits.max_funding_rate:
        return f"资金费率绝对值 {_format(rate)} 超过上限 {_format(facts.limits.max_funding_rate)}"
    return None


def _liquidation_distance(facts: _Facts) -> str | None:
    if not facts.opening:
        return None
    if facts.request.liquidation_price is None:
        return "缺少预估强平价, 无法确认强平距离"
    price = facts.request.reference_price
    liquidation = facts.request.liquidation_price
    distance = (
        (price - liquidation) / price if facts.direction == LONG else (liquidation - price) / price
    )
    if distance < facts.limits.min_liquidation_distance:
        return (
            f"预估强平价 {_format(liquidation)} 距现价 {_format(price)} 的距离 "
            f"{_format(distance)} 小于阈值 {_format(facts.limits.min_liquidation_distance)}"
        )
    return None


RULE_CATALOG: tuple[RuleSpec, ...] = (
    RuleSpec("order_amount_ratio", RuleScope.ALL, "单笔金额占权益上限", _order_amount_ratio),
    RuleSpec("instrument_weight", RuleScope.ALL, "单标的权重上限", _instrument_weight),
    RuleSpec("max_positions", RuleScope.ALL, "最多持仓数量", _max_positions),
    RuleSpec("duplicate_signal", RuleScope.ALL, "重复信号防护", _duplicate_signal),
    RuleSpec("qty_precision", RuleScope.ALL, "数量精度", _qty_precision),
    RuleSpec("price_precision", RuleScope.ALL, "价格精度", _price_precision),
    RuleSpec("gross_exposure", RuleScope.ALL, "总敞口上限", _gross_exposure),
    RuleSpec("net_exposure", RuleScope.ALL, "净敞口上限", _net_exposure),
    RuleSpec("concentration", RuleScope.ALL, "单一产品集中度上限", _concentration),
    RuleSpec("correlation_risk", RuleScope.ALL, "相关性风险上限", _correlation_risk),
    RuleSpec(
        "multi_strategy_duplicate",
        RuleScope.ALL,
        "多策略重复持仓上限",
        _multi_strategy_duplicate,
    ),
    RuleSpec("max_drawdown", RuleScope.ALL, "组合最大回撤上限", _max_drawdown),
    RuleSpec("available_balance", RuleScope.NO_MARGIN, "现货买入可用余额", _available_balance),
    RuleSpec("leverage", RuleScope.MARGIN, "杠杆上限", _leverage),
    RuleSpec("funding_rate", RuleScope.FUNDING, "资金费率绝对值上限", _funding_rate),
    RuleSpec(
        "liquidation_distance",
        RuleScope.MARGIN,
        "强平距离下限",
        _liquidation_distance,
    ),
)


def applicable_rule_names(inst_type: str) -> tuple[str, ...]:
    """这一类别实际参与判定的规则, 按规则表顺序。"""

    rules = trading_rules(inst_type)
    return tuple(spec.name for spec in RULE_CATALOG if _scope_applies(spec.scope, rules))


def rule_applicability() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """每条规则适用的类别集合；集合为空说明规则写错了, 测试会直接变红。"""

    categories = trading_categories()
    return tuple(
        (
            spec.name,
            tuple(
                category
                for category in categories
                if _scope_applies(spec.scope, trading_rules(category))
            ),
        )
        for spec in RULE_CATALOG
    )


def evaluate(
    request: TradeRequest,
    instrument: Instrument,
    context: RiskContext,
    limits: RiskLimits,
    *,
    halted: bool,
) -> RiskDecision:
    """对一条下单请求做完整判定；不构造订单、不写库。

    紧急停止只拦新开仓：`reduce_only` 的平仓请求照常通过其它检查。
    """

    rules = trading_rules(instrument.inst_type)
    specs = tuple(spec for spec in RULE_CATALOG if _scope_applies(spec.scope, rules))
    notional = _notional(request, instrument)
    facts = _Facts(
        request=request,
        instrument=instrument,
        context=context,
        limits=limits,
        rules=rules,
        notional=notional,
    )

    checked = [spec.name for spec in specs]
    violations: list[RuleViolation] = []
    if halted and not request.reduce_only:
        checked.insert(0, "emergency_stop")
        violations.append(
            RuleViolation(
                "emergency_stop",
                f"紧急停止已打开, 策略 {request.instance_id} 的新开仓信号被拒绝",
            )
        )
    for spec in specs:
        detail = spec.check(facts)
        if detail is not None:
            violations.append(RuleViolation(spec.name, detail))

    return RiskDecision(
        allowed=not violations,
        checked_rules=tuple(checked),
        violations=tuple(violations),
    )


def _notional(request: TradeRequest, instrument: Instrument) -> Decimal:
    """名义价值：现货为数量 × 价格；永续再乘合约面值。"""

    price = request.reference_price
    unit = trading_rules(instrument.inst_type).qty_unit
    if unit == UNIT_CONTRACT:
        if instrument.ct_val is None or instrument.ct_val <= ZERO:
            raise ValidationError(f"标的 {instrument.symbol} 缺少有效的合约面值")
        return request.qty * instrument.ct_val * price
    return request.qty * price


def _require_positive_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= ZERO:
        raise ValidationError(f"{name} 必须是正有限 Decimal, 实际 {value!r}")


def _require_non_negative_decimal(value: object, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
        raise ValidationError(f"{name} 必须是非负有限 Decimal, 实际 {value!r}")
