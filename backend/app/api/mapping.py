"""API 边界上的形状转换：持久化实体 → 契约模型。

只在 `app/api` 内复用；业务模块不感知 HTTP 契约，也不依赖这些模型。
"""

from __future__ import annotations

from decimal import Decimal

from app.api.schemas.common import InstrumentInfo, InstrumentRef
from app.instrument import Instrument

__all__ = ["decimal_str", "instrument_info", "instrument_ref"]


def decimal_str(value: Decimal) -> str:
    """`Decimal` → 定点字符串：不带指数、不丢精度，符合契约的 Decimal 形状。"""

    return format(value.normalize(), "f")


def instrument_ref(row: Instrument) -> InstrumentRef:
    """标的表实体的最小契约视图，用于搜索与列表。"""

    return InstrumentRef(
        inst_id=row.symbol,
        inst_type=row.inst_type,
        product_key=row.product_key,
        asset_type=row.asset_type,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
    )


def instrument_info(row: Instrument) -> InstrumentInfo:
    """标的表实体的完整契约视图，带上自选与详情都需要的交易参数。"""

    return InstrumentInfo(
        inst_id=row.symbol,
        inst_type=row.inst_type,
        product_key=row.product_key,
        asset_type=row.asset_type,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        tick_size=_optional_decimal(row.tick_size),
        lot_size=_optional_decimal(row.lot_size),
        min_order_size=_optional_decimal(row.min_order_size),
        listing_time=row.listing_time,
        trading_status=row.trading_status,
        max_leverage=_optional_decimal(row.max_lever),
    )


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else decimal_str(value)
