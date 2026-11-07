"""成本模型（纯函数）：手续费、滑点与资金费。

口径固定、可手算：

- 成交价 = bar `close`；滑点按方向调整成交价（买入抬高、卖出压低），
  同时把滑点金额单独记账用于成本归因，**不重复扣减**（已体现在成交价里）。
- 手续费按「角色」取一档费率（`taker_fee_bps` / `maker_fee_bps`），
  建仓与平仓各按成交名义金额计一次。
- 资金费按持仓跨越的 8 小时 UTC 边界（00:00 / 08:00 / 16:00）计次；
  多头支付、空头收取，正数表示成本。P1 没有资金费采集，费率只能是常数，
  由 `params.funding_assumption="constant"` 显式声明。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

BPS = Decimal(10000)
FUNDING_PERIOD_SECONDS = 8 * 3600
FUNDING_ANCHOR = datetime(1970, 1, 1, tzinfo=UTC)  # 8h 边界与 UTC 零点对齐

VALID_FEE_ROLES = ("taker", "maker")
VALID_SIDES = ("long", "short")


@dataclass(frozen=True, slots=True)
class CostModel:
    """一次回测的成本假设；所有费率单位为 bps（万分之一）。"""

    taker_fee_bps: Decimal = Decimal(0)
    maker_fee_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)
    funding_bps_per_period: Decimal = Decimal(0)
    funding_enabled: bool = True
    fee_role: str = "taker"

    def fee_bps(self) -> Decimal:
        if self.fee_role == "maker":
            return self.maker_fee_bps
        return self.taker_fee_bps

    def as_dict(self) -> dict[str, Any]:
        return {
            "taker_fee_bps": _text(self.taker_fee_bps),
            "maker_fee_bps": _text(self.maker_fee_bps),
            "slippage_bps": _text(self.slippage_bps),
            "funding_bps_per_period": _text(self.funding_bps_per_period),
            "funding": self.funding_enabled,
            "fee_role": self.fee_role,
        }


def _text(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def execution_prices(
    side: str, close_in: Decimal, close_out: Decimal, slippage_bps: Decimal
) -> tuple[Decimal, Decimal]:
    """把理论收盘价换成含滑点的实际成交价（买入抬高、卖出压低）。"""

    if side not in VALID_SIDES:
        raise ValueError(f"unknown side: {side!r}")
    slip = Decimal(slippage_bps) / BPS
    if side == "long":
        return close_in * (Decimal(1) + slip), close_out * (Decimal(1) - slip)
    return close_in * (Decimal(1) - slip), close_out * (Decimal(1) + slip)


def fee_cost(fee_bps: Decimal, entry_notional: Decimal, exit_notional: Decimal) -> Decimal:
    """一次完整来回的手续费；名义金额取绝对值，多空同一口径。"""

    return abs(Decimal(fee_bps)) / BPS * (abs(entry_notional) + abs(exit_notional))


def slippage_cost(
    slippage_bps: Decimal, entry_notional: Decimal, exit_notional: Decimal
) -> Decimal:
    """滑点金额（成本归因用；已包含在成交价里，不再从净收益里二次扣减）。"""

    return abs(Decimal(slippage_bps)) / BPS * (abs(entry_notional) + abs(exit_notional))


def funding_cost(
    side: str,
    funding_bps_per_period: Decimal,
    notional: Decimal,
    crossings: int,
) -> Decimal:
    """资金费成本：多头为正（支付），空头为负（收取）。"""

    if side not in VALID_SIDES:
        raise ValueError(f"unknown side: {side!r}")
    if crossings <= 0:
        return Decimal(0)
    sign = Decimal(1) if side == "long" else Decimal(-1)
    return sign * Decimal(funding_bps_per_period) / BPS * abs(notional) * crossings


def count_funding_crossings(entry_ts: datetime, exit_ts: datetime) -> int:
    """持仓区间 `(entry_ts, exit_ts]` 内跨过的 8h UTC 边界数。

    恰好在边界建仓不计当次（资金费在边界结算，建仓不在持仓前），
    恰好在边界平仓计当次。区间两个端点都按 UTC 处理。
    """

    if exit_ts <= entry_ts:
        return 0
    entry_seconds = _utc_seconds(entry_ts)
    exit_seconds = _utc_seconds(exit_ts)
    first = (entry_seconds // FUNDING_PERIOD_SECONDS + 1) * FUNDING_PERIOD_SECONDS
    if first > exit_seconds:
        return 0
    return (exit_seconds - first) // FUNDING_PERIOD_SECONDS + 1


def _utc_seconds(moment: datetime) -> int:
    delta: timedelta = moment - FUNDING_ANCHOR
    return delta.days * 86400 + delta.seconds


__all__ = [
    "BPS",
    "FUNDING_PERIOD_SECONDS",
    "VALID_FEE_ROLES",
    "VALID_SIDES",
    "CostModel",
    "count_funding_crossings",
    "execution_prices",
    "fee_cost",
    "funding_cost",
    "slippage_cost",
]
