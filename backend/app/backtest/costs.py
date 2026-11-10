"""成本模型（纯函数）：手续费与滑点。

口径固定、可手算：

- 成交价 = bar `close`；滑点按方向调整成交价（买入抬高、卖出压低），
  同时把滑点金额单独记账用于成本归因，**不重复扣减**（已体现在成交价里）。
- 手续费按「角色」取一档费率（`taker_fee_bps` / `maker_fee_bps`），
  建仓与平仓各按成交名义金额计一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

BPS = Decimal(10000)

VALID_FEE_ROLES = ("taker", "maker")
VALID_SIDES = ("long", "short")


@dataclass(frozen=True, slots=True)
class CostModel:
    """一次回测的成本假设；所有费率单位为 bps（万分之一）。"""

    taker_fee_bps: Decimal = Decimal(0)
    maker_fee_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)
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


__all__ = [
    "BPS",
    "VALID_FEE_ROLES",
    "VALID_SIDES",
    "CostModel",
    "execution_prices",
    "fee_cost",
    "slippage_cost",
]
