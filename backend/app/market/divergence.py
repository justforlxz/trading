"""同一产品在两个行情来源上的价格偏离：纯函数，超阈值返回带数值的告警。

同一个产品（`product_key`）可能同时有 OKX 行情与美股代理行情：前者是标的化合约的
成交价，后者是真实美股的参考价。两者长期应当接近，短时可能因流动性、交易时段、
结算方式而偏离——偏离本身就是需要人看一眼的信号，不是需要被「融合」掉的噪音。

本模块只算数，不取数、不融合、不做决策。偏离度以**参考来源**（`reference`）为
分母：`|other - reference| / reference × 100`，保留两位小数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.core import ValidationError

__all__ = ["DEFAULT_THRESHOLD_PCT", "DivergenceAlert", "Quote", "divergence"]

# 默认阈值：同一产品的两个来源价差达到 3% 就值得看一眼。
DEFAULT_THRESHOLD_PCT = Decimal("3")

_PERCENT = Decimal("100")
_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Quote:
    """某一来源对一个产品的最新报价。

    `source` 与 `candles.source` 同值；`ts` 是这个价格对应的时刻，必须带时区——
    没有时间戳的价格无法判断新鲜度，也不能和另一个来源比。
    """

    product_key: str
    source: str
    price: Decimal
    ts: datetime

    def __post_init__(self) -> None:
        if not self.product_key.strip():
            raise ValidationError("报价缺少产品键")
        if not self.source.strip():
            raise ValidationError("报价缺少数据来源")
        if self.price <= 0:
            raise ValidationError(f"报价必须为正, 实际 {self.price}")
        if self.ts.tzinfo is None:
            raise ValidationError("报价的 ts 必须带时区")


@dataclass(frozen=True, slots=True)
class DivergenceAlert:
    """一次超阈值的跨源偏离；两个原始报价原样附带，便于人核对。"""

    product_key: str
    reference: Quote
    other: Quote
    deviation_pct: Decimal
    threshold_pct: Decimal


def divergence(
    reference: Quote,
    other: Quote,
    *,
    threshold_pct: Decimal = DEFAULT_THRESHOLD_PCT,
) -> DivergenceAlert | None:
    """两个来源的同一产品偏离度；达到或超过阈值返回告警，否则返回 `None`。

    `reference` 是该时段的参考来源（代币化股票正常时段是美股代理行情），偏离度以
    它为分母，因此「3%」的方向是固定的，不随调用顺序取反。
    """

    if threshold_pct < 0:
        raise ValidationError(f"偏离阈值不能为负, 实际 {threshold_pct}")
    if reference.product_key.strip().upper() != other.product_key.strip().upper():
        raise ValidationError(
            f"偏离度只能比同一产品:{reference.product_key!r} 与 {other.product_key!r}"
        )
    if reference.source == other.source:
        raise ValidationError(f"偏离度需要两个不同来源, 实际都是 {reference.source!r}")

    deviation = (abs(other.price - reference.price) / reference.price * _PERCENT).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if deviation < threshold_pct:
        return None
    return DivergenceAlert(
        product_key=reference.product_key.strip().upper(),
        reference=reference,
        other=other,
        deviation_pct=deviation,
        threshold_pct=threshold_pct,
    )
