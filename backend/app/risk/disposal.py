"""分级风险处置：把一次触发的风险规则换算成严重程度与处置动作。

本模块是**纯函数**：不读库、不构造订单、不改状态。输入是规则名与一份组合事实，
输出是处置计划；执行动作、覆盖待批准申请、写风险事件都在 `app.risk.actions`。

适用类别只问 `trading_rules(inst_type)` 的 `has_funding` / `has_margin`，这里不写
任何具体类别名。资金费只在有资金费的类别参与，强平距离只在有保证金的类别参与，
可用余额只在没有保证金的类别参与。

阈值口径（均为「占权益的比率」或「相对既有上限的倍数」）：

- 单笔金额 / 单标的权重：超过上限但未到 1.2 倍为轻，达到 1.2 倍为中。
- 资金费率：绝对值超过上限即为轻。
- 组合回撤：达到 `max_drawdown` 的一半为中，达到 `max_drawdown` 为严重。
- 强平距离：小于 `min_liquidation_distance` 为中，小于它的一半为严重。
- 可用余额：低于权益的 20% 为轻，低于 10% 为中，低于 5% 为严重。

阈值配置为 0 表示不允许任何超出：实际值越过 0 就按对应规则判定，与 T6.1 的判定
条件保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.core import ValidationError
from app.instrument import trading_rules
from app.risk.rules import RiskLimits

__all__ = [
    "DisposalAction",
    "DisposalContext",
    "DisposalPlan",
    "Severity",
    "plan",
]

ZERO = Decimal(0)

RULE_ORDER_AMOUNT = "order_amount_ratio"
RULE_INSTRUMENT_WEIGHT = "instrument_weight"
RULE_DRAWDOWN = "max_drawdown"
RULE_FUNDING = "funding_rate"
RULE_LIQUIDATION = "liquidation_distance"
RULE_MARGIN_INSUFFICIENT = "margin_insufficient"
RULE_AVAILABLE_BALANCE = "available_balance"

LIGHT_MULTIPLE = Decimal("1.2")
DRAWDOWN_MEDIUM_MULTIPLE = Decimal("0.5")
LIQUIDATION_SEVERE_MULTIPLE = Decimal("0.5")
BALANCE_WARN_MULTIPLE = Decimal("0.20")
BALANCE_MEDIUM_MULTIPLE = Decimal("0.10")
BALANCE_SEVERE_MULTIPLE = Decimal("0.05")


class Severity(StrEnum):
    """处置严重程度；`light` / `medium` / `severe` 三档。"""

    LIGHT = "light"
    MEDIUM = "medium"
    SEVERE = "severe"


class DisposalAction(StrEnum):
    """一次处置要执行的动作。"""

    WARN = "warn"
    REDUCE = "reduce"
    STOP_LOSS = "stop_loss"
    LIQUIDATE = "liquidate"
    HALT_ALL = "halt_all"


@dataclass(frozen=True, slots=True)
class DisposalContext:
    """判定一次处置需要的组合事实。

    `order_amount` 与 `instrument_weight` 是风控算出的「预计值」，不是比率；
    `drawdown`、`funding_rate`、`liquidation_distance` 与 `available_balance`
    都按原始口径传入。`limits` 与 T6.1 共用同一份阈值。
    """

    inst_type: str
    inst_id: str
    product_key: str
    equity: Decimal
    strategy_equity: Decimal | None = None
    drawdown: Decimal = ZERO
    order_amount: Decimal | None = None
    instrument_weight: Decimal | None = None
    funding_rate: Decimal | None = None
    liquidation_distance: Decimal | None = None
    available_balance: Decimal | None = None
    limits: RiskLimits = field(default_factory=RiskLimits)

    def __post_init__(self) -> None:
        if not self.inst_id.strip():
            raise ValidationError("处置必须给出标的")
        if not self.product_key.strip():
            raise ValidationError("处置必须给出产品键")
        trading_rules(self.inst_type)
        for name in (
            "equity",
            "drawdown",
            "order_amount",
            "instrument_weight",
            "available_balance",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
                raise ValidationError(f"{name} 必须是非负有限 Decimal, 实际 {value!r}")
        if self.strategy_equity is not None and (
            not isinstance(self.strategy_equity, Decimal)
            or not self.strategy_equity.is_finite()
            or self.strategy_equity < ZERO
        ):
            raise ValidationError(
                f"strategy_equity 必须是非负有限 Decimal, 实际 {self.strategy_equity!r}"
            )
        for name in ("funding_rate", "liquidation_distance"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValidationError(f"{name} 必须是有限 Decimal, 实际 {value!r}")

    @property
    def strategy_budget(self) -> Decimal:
        """策略级限额的分母：有策略预算就用预算，否则退回组合权益。"""

        return self.strategy_equity if self.strategy_equity is not None else self.equity


@dataclass(frozen=True, slots=True)
class DisposalPlan:
    """一次处置的完整结论；`actions` 按执行顺序排列。"""

    rule: str
    severity: Severity
    actions: tuple[DisposalAction, ...]
    detail: str
    inst_id: str
    product_key: str
    inst_type: str

    @property
    def action_text(self) -> str:
        """写入 `risk_events.action` 的稳定文本。"""

        return ",".join(action.value for action in self.actions)


def plan(rule: str, context: DisposalContext) -> DisposalPlan | None:
    """把一条触发的规则换算成处置计划；规则不适用或未越线时返回 `None`。"""

    rules = trading_rules(context.inst_type)
    if rule == RULE_FUNDING and not rules.has_funding:
        return None
    if rule in (RULE_LIQUIDATION, RULE_MARGIN_INSUFFICIENT) and not rules.has_margin:
        return None
    if rule == RULE_AVAILABLE_BALANCE and rules.has_margin:
        return None

    severity = _severity(rule, context)
    if severity is None:
        return None
    return DisposalPlan(
        rule=rule,
        severity=severity,
        actions=_actions(rule, severity),
        detail=_detail(rule, severity, context),
        inst_id=context.inst_id,
        product_key=context.product_key,
        inst_type=context.inst_type,
    )


def _severity(rule: str, context: DisposalContext) -> Severity | None:
    if rule in (RULE_ORDER_AMOUNT, RULE_INSTRUMENT_WEIGHT):
        return _exposure_severity(rule, context)
    if rule == RULE_FUNDING:
        return _funding_severity(context)
    if rule == RULE_DRAWDOWN:
        return _drawdown_severity(context)
    if rule == RULE_LIQUIDATION:
        return _liquidation_severity(context)
    if rule == RULE_MARGIN_INSUFFICIENT:
        return Severity.SEVERE
    if rule == RULE_AVAILABLE_BALANCE:
        return _balance_severity(context)
    raise ValidationError(f"未知的处置规则 {rule!r}")


def _exposure_severity(rule: str, context: DisposalContext) -> Severity | None:
    if rule == RULE_ORDER_AMOUNT:
        value = context.order_amount
        limit = context.limits.max_order_ratio * context.strategy_budget
    else:
        value = context.instrument_weight
        limit = context.limits.max_instrument_weight * context.strategy_budget
    if value is None:
        raise ValidationError(f"规则 {rule} 需要对应的预计敞口值")
    if value <= limit:
        return None
    return Severity.LIGHT if value < limit * LIGHT_MULTIPLE else Severity.MEDIUM


def _funding_severity(context: DisposalContext) -> Severity | None:
    if context.funding_rate is None:
        raise ValidationError("资金费处置需要当前资金费率")
    if abs(context.funding_rate) > context.limits.max_funding_rate:
        return Severity.LIGHT
    return None


def _drawdown_severity(context: DisposalContext) -> Severity | None:
    limit = context.limits.max_drawdown
    if context.drawdown <= ZERO:
        return None
    if context.drawdown >= limit:
        return Severity.SEVERE
    if context.drawdown >= limit * DRAWDOWN_MEDIUM_MULTIPLE:
        return Severity.MEDIUM
    return None


def _liquidation_severity(context: DisposalContext) -> Severity | None:
    if context.liquidation_distance is None:
        raise ValidationError("强平距离处置需要当前强平距离")
    limit = context.limits.min_liquidation_distance
    if context.liquidation_distance < limit * LIQUIDATION_SEVERE_MULTIPLE:
        return Severity.SEVERE
    if context.liquidation_distance < limit:
        return Severity.MEDIUM
    return None


def _balance_severity(context: DisposalContext) -> Severity | None:
    if context.available_balance is None:
        raise ValidationError("可用余额处置需要当前可用余额")
    equity = context.equity
    if context.available_balance < equity * BALANCE_SEVERE_MULTIPLE:
        return Severity.SEVERE
    if context.available_balance < equity * BALANCE_MEDIUM_MULTIPLE:
        return Severity.MEDIUM
    if context.available_balance < equity * BALANCE_WARN_MULTIPLE:
        return Severity.LIGHT
    return None


def _actions(rule: str, severity: Severity) -> tuple[DisposalAction, ...]:
    if severity is Severity.LIGHT:
        return (DisposalAction.WARN,)
    if severity is Severity.MEDIUM:
        return (DisposalAction.REDUCE,)
    if rule in (RULE_LIQUIDATION, RULE_MARGIN_INSUFFICIENT):
        return (DisposalAction.STOP_LOSS, DisposalAction.LIQUIDATE)
    if rule == RULE_AVAILABLE_BALANCE:
        return (DisposalAction.LIQUIDATE,)
    return (DisposalAction.STOP_LOSS, DisposalAction.HALT_ALL)


def _detail(rule: str, severity: Severity, context: DisposalContext) -> str:
    labels = {
        RULE_ORDER_AMOUNT: "单笔金额",
        RULE_INSTRUMENT_WEIGHT: "单标的权重",
        RULE_DRAWDOWN: "组合回撤",
        RULE_FUNDING: "资金费率绝对值",
        RULE_LIQUIDATION: "强平距离",
        RULE_MARGIN_INSUFFICIENT: "可用保证金",
        RULE_AVAILABLE_BALANCE: "可用余额",
    }
    return f"{labels[rule]}触发{severity.value}处置, 标的 {context.inst_id}"
