"""按数量单位换算持仓名义价值。

交易所永续的数量单位是合约张数，现货与手动持仓的数量单位是基础币数量。两类数量
不能直接相乘，必须由标的类别给出单位，再按合约面值与乘数换算。这里只做纯计算，
不读库、不联网；缺价格或合约规格时返回 `None`，不用 0 冒充。
"""

from __future__ import annotations

from decimal import Decimal

from app.core import ValidationError

__all__ = ["QTY_UNIT_BASE", "QTY_UNIT_CONTRACT", "notional_value"]

QTY_UNIT_BASE = "base"
QTY_UNIT_CONTRACT = "contract"


def notional_value(
    *,
    size: Decimal,
    price: Decimal | None,
    qty_unit: str,
    ct_val: Decimal | None = None,
    ct_mult: Decimal | None = None,
) -> Decimal | None:
    """按数量单位换算名义价值；缺价格或合约规格时返回 `None`。"""

    if price is None:
        return None
    if qty_unit == QTY_UNIT_BASE:
        return abs(size) * price
    if qty_unit == QTY_UNIT_CONTRACT:
        if ct_val is None or ct_mult is None:
            return None
        return abs(size) * price * ct_val * ct_mult
    raise ValidationError(f"未知数量单位 {qty_unit!r}")
