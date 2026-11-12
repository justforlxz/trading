"""Manual 模式：把信号与目标组合变成交易计划，并记录人工确认。

三条固定口径：

- **没有确认就不产生订单**。计划本身只是数据；确认记录绑定 `plan_id`、`version` 与
  计划内容摘要，计划改版后旧确认不再适用。
- **数量只换算一次**。每条腿的权重与资金在这里换成可下数量，执行层不再按价格或
  精度重复取整，避免同一条腿在两层得到两个不同的数字。
- **幂等键由计划派生**。同一个计划版本重复确认必须落到同一串 `clientOrderId`，且
  形状满足上游要求的 1..32 位字母数字，不能靠随机数或进程内序号。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal

from app.core import Clock, Conflict, InstrumentRef, Signal, SystemClock, ValidationError
from app.execution.model import ConfirmationRecord, PlanLeg, TradePlan
from app.strategy import TargetPortfolio, target_quantity

__all__ = [
    "build_plan",
    "client_order_id",
    "confirm",
    "plan_digest",
    "require_confirmation",
]

ZERO = Decimal(0)


def build_plan(
    *,
    plan_id: str,
    version: int,
    strategy_id: str,
    target: TargetPortfolio,
    signals: Iterable[Signal],
    instruments: Mapping[str, InstrumentRef],
    prices: Mapping[str, Decimal],
    capital: Decimal,
    price_caps: Mapping[str, Decimal] | None = None,
) -> TradePlan:
    """把一组信号与目标组合变成可确认的交易计划。

    `instruments` 以 `product_key` 为键，由调用方选择本次要交易的形态（现货或永续）；
    执行层不替调用方决定同一个产品该选哪一种。

    每条目标腿都必须有一条同标的、同方向的信号；价格上限按 `product_key` 给出，缺省
    表示市价单。信号与目标方向不一致时直接报错，不悄悄改方向或跳过错配的腿。
    """

    signals_by_inst: dict[str, Signal] = {}
    for signal in signals:
        if not isinstance(signal, Signal):
            raise ValidationError(f"信号只能是 Signal, 实际 {type(signal).__name__}")
        if signal.inst_id in signals_by_inst:
            raise ValidationError(f"同一标的出现多条信号:{signal.inst_id}")
        signals_by_inst[signal.inst_id] = signal

    caps = price_caps or {}
    legs: list[PlanLeg] = []
    for target_leg in target.legs:
        instrument = instruments.get(target_leg.product_key)
        if instrument is None:
            raise ValidationError(f"目标腿 {target_leg.product_key} 没有对应的标的")
        signal = signals_by_inst.get(instrument.inst_id)
        if signal is None:
            raise ValidationError(f"标的 {instrument.inst_id} 没有对应信号, 不能生成计划")
        if signal.side != target_leg.side:
            raise ValidationError(
                f"标的 {instrument.inst_id} 的信号方向 {signal.side} 与目标方向"
                f" {target_leg.side} 不一致"
            )
        price = prices.get(instrument.inst_id)
        if price is None:
            raise ValidationError(f"标的 {instrument.inst_id} 没有价格, 不能换算数量")
        quantity = target_quantity(target_leg, instrument, price=price, capital=capital).qty
        if quantity <= ZERO:
            raise ValidationError(
                f"标的 {instrument.inst_id} 的目标数量按 lot_size 取整后为 0, 无法下单"
            )
        side = "buy" if target_leg.side == "long" else "sell"
        price_cap = caps.get(target_leg.product_key)
        if price_cap is not None and (
            not isinstance(price_cap, Decimal) or not price_cap.is_finite() or price_cap <= ZERO
        ):
            raise ValidationError(
                f"标的 {target_leg.product_key} 的价格上限必须为正, 实际 {price_cap!r}"
            )
        legs.append(
            PlanLeg(
                product_key=target_leg.product_key,
                inst_id=instrument.inst_id,
                inst_type=instrument.inst_type,
                side=side,
                qty=quantity,
                strategy_id=strategy_id,
                price_cap=price_cap,
            )
        )
    return TradePlan(plan_id=plan_id, version=version, as_of=target.as_of, legs=tuple(legs))


def client_order_id(plan: TradePlan, leg: PlanLeg) -> str:
    """由计划与腿派生幂等键：同一份计划版本永远得到同一串键。

    用 SHA-256 的十六进制前缀而不是 Python 的 `hash()`：后者带进程随机种子，重启后
    同一个计划会得到不同的键，上游就无法把重复确认认成同一张单。
    """

    price = "" if leg.price_cap is None else format(leg.price_cap, "f")
    payload = "|".join(
        (
            plan.plan_id,
            str(plan.version),
            leg.inst_id,
            leg.side,
            format(leg.qty, "f"),
            price,
            leg.strategy_id,
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:31]
    return f"m{digest}"


def plan_digest(plan: TradePlan) -> str:
    """计算计划内容的摘要，用于判断确认后计划内容是否发生变化。

    摘要覆盖计划标识、版本、时间与每条腿的全部下单字段；腿的顺序参与计算。调用方
    沿用同一个 `plan_id` 与 `version` 重新生成计划时，只要数量、方向、价格或标的
    有任何变化，摘要就会不同。
    """

    payload = [plan.plan_id, str(plan.version), plan.as_of.isoformat()]
    for leg in plan.legs:
        payload.extend(
            (
                leg.product_key,
                leg.inst_id,
                leg.inst_type,
                leg.side,
                format(leg.qty, "f"),
                "" if leg.price_cap is None else format(leg.price_cap, "f"),
                leg.strategy_id,
            )
        )
    return hashlib.sha256("\x1f".join(payload).encode("utf-8")).hexdigest()


def confirm(
    plan: TradePlan,
    *,
    confirmed_by: str,
    now: datetime | None = None,
    clock: Clock | None = None,
) -> ConfirmationRecord:
    """记录一次人工确认；`now` 未给出时从注入的时钟取时间。"""

    if now is None:
        now = (clock or SystemClock()).now()
    return ConfirmationRecord(
        plan_id=plan.plan_id,
        plan_version=plan.version,
        plan_digest=plan_digest(plan),
        confirmed_by=confirmed_by,
        confirmed_at=now,
    )


def require_confirmation(plan: TradePlan, record: ConfirmationRecord) -> None:
    """确认记录必须对应这份计划的这个版本，否则拒绝下单。"""

    if record.plan_id != plan.plan_id:
        raise Conflict(f"确认记录属于计划 {record.plan_id}, 不是 {plan.plan_id}")
    if record.plan_version != plan.version:
        raise Conflict(f"确认记录绑定计划版本 {record.plan_version}, 当前版本是 {plan.version}")
    if record.plan_digest != plan_digest(plan):
        raise Conflict("确认记录绑定的计划内容与当前计划不一致, 请重新确认")
