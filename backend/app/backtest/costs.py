"""成本模型（纯函数）：手续费与滑点。

口径固定、可手算：

- 成交价 = bar `close`；滑点与买卖价差按方向调整成交价（买入抬高、卖出压低），
  同时把滑点金额单独记账用于成本归因，**不重复扣减**（已体现在成交价里）。
- 买卖价差按「半价差过一次盘」计：买入付半价差、卖出让半价差，一次完整来回正好
  付一个价差。它和滑点一样只影响成交价，不单独再从净值里扣一次。
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
VALID_TRADE_SIDES = ("buy", "sell")


@dataclass(frozen=True, slots=True)
class CostModel:
    """一次回测的成本假设；所有费率单位为 bps（万分之一）。"""

    taker_fee_bps: Decimal = Decimal(0)
    maker_fee_bps: Decimal = Decimal(0)
    slippage_bps: Decimal = Decimal(0)
    spread_bps: Decimal = Decimal(0)
    fee_role: str = "taker"

    def execution_bps(self) -> Decimal:
        """一次成交对价格的调整幅度：滑点全额 + 半价差，单位 bps。

        单笔成交只穿过半个价差（买付卖价、卖付买价），因此价差按一半计；一次完整
        来回正好穿过两次，合计一个价差。
        """

        return self.slippage_bps + self.spread_bps / Decimal(2)

    def fee_bps(self) -> Decimal:
        if self.fee_role == "maker":
            return self.maker_fee_bps
        return self.taker_fee_bps

    def as_dict(self) -> dict[str, Any]:
        return {
            "taker_fee_bps": decimal_text(self.taker_fee_bps),
            "maker_fee_bps": decimal_text(self.maker_fee_bps),
            "slippage_bps": decimal_text(self.slippage_bps),
            "spread_bps": decimal_text(self.spread_bps),
            "fee_role": self.fee_role,
        }


def decimal_text(value: Decimal) -> str:
    """`Decimal` 的规范文本：去掉尾随零、不用科学计数法。对外契约与摘要都只认这个形状。"""

    return format(Decimal(value).normalize(), "f")


def execution_price(trade_side: str, price: Decimal, slippage_bps: Decimal) -> Decimal:
    """单笔成交价：买入抬高、卖出压低，滑点以 bps 计。

    回测引擎逐笔成交，成交方向是「买」或「卖」；多空只是持仓方向，不改变「买入
    抬高、卖出压低」这条口径，因此这里不接收 long/short。
    """

    if trade_side not in VALID_TRADE_SIDES:
        raise ValueError(f"unknown trade side: {trade_side!r}")
    slip = Decimal(slippage_bps) / BPS
    if trade_side == "buy":
        return Decimal(price) * (Decimal(1) + slip)
    return Decimal(price) * (Decimal(1) - slip)


def execution_prices(
    side: str, close_in: Decimal, close_out: Decimal, slippage_bps: Decimal
) -> tuple[Decimal, Decimal]:
    """把理论收盘价换成含滑点的实际成交价（买入抬高、卖出压低）。

    建仓与平仓各是一个方向：多头买入建仓、卖出平仓，空头反过来。两条腿的公式都由
    `execution_price` 给出，本函数只负责把建仓/平仓配到买卖方向上。
    """

    if side not in VALID_SIDES:
        raise ValueError(f"unknown side: {side!r}")
    if side == "long":
        return (
            execution_price("buy", close_in, slippage_bps),
            execution_price("sell", close_out, slippage_bps),
        )
    return (
        execution_price("sell", close_in, slippage_bps),
        execution_price("buy", close_out, slippage_bps),
    )


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
    "VALID_TRADE_SIDES",
    "CostModel",
    "execution_price",
    "execution_prices",
    "fee_cost",
    "slippage_cost",
]
