"""标的的持久化模型与上游分类映射。

一个 `Instrument` 同时覆盖代币化股票、代币化商品与加密资产的现货/永续：
形态只体现在 `inst_type`（SPOT / SWAP），资产类别来自上游 `instCategory`
（`inst_category`），不看符号前缀。

现货与永续是同一产品的两种形态，靠 `product_key` 配对：代币化股票现货的
`baseCcy` 带一个 `X` 标记（`XAAPL`），永续的标的币种在 `ctValCcy`（`AAPL`）；
加密资产的 base 本身就可能以 X 开头（`XRP`），因此**去掉 X 只发生在
`instCategory == 3` 的现货上**，其余类别原样使用上游币种。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core import InstrumentRef, ValidationError
from app.db import Base, DecimalText, UtcDateTime

__all__ = ["Instrument", "InstrumentPair"]

EXCHANGE = "okx"

SPOT = "SPOT"
SWAP = "SWAP"
INST_TYPES = frozenset({SPOT, SWAP})

# OKX `instCategory`：3 = 代币化股票/ETF，1 = 加密资产，4 = 代币化商品。
TOKENIZED_EQUITY_CATEGORY = "3"
_ASSET_TYPES: dict[str, str] = {
    "3": "tokenized_equity",
    "1": "crypto",
    "4": "commodity_token",
}
UNKNOWN_ASSET_TYPE = "unknown"


class Instrument(Base):
    """交易所标的的静态快照（一个产品的一种形态一行）。

    `symbol` 就是交易所的 `instId`，是唯一身份；`product_key` 才是同一产品跨
    形态的配对键。`base_currency` 取配对键本身，因此同一产品的现货与永续在
    分析层看到的是同一个标的币种，形态差异不出现在这里。

    精度字段与 `data_start` 可以为空：尚未开盘的标的（`preopen`）上游不下发
    精度、也还没有行情，此时如实留空而不是伪造数值。
    """

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(64), primary_key=True)
    inst_type: Mapped[str] = mapped_column(String(16), index=True)
    product_key: Mapped[str] = mapped_column(String(32), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    exchange: Mapped[str] = mapped_column(String(16), default=EXCHANGE)
    base_currency: Mapped[str] = mapped_column(String(32))
    quote_currency: Mapped[str] = mapped_column(String(16))
    tick_size: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    lot_size: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    min_order_size: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    listing_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    trading_status: Mapped[str] = mapped_column(String(16))
    data_start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ct_val: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    ct_mult: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    ct_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    max_lever: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    settle_ccy: Mapped[str | None] = mapped_column(String(16), nullable=True)


@dataclass(frozen=True, slots=True)
class InstrumentPair:
    """同一产品的两种形态；缺哪一侧就是 `None`，绝不凭空拼造。"""

    product_key: str
    spot: Instrument | None
    swap: Instrument | None

    def counterpart(self, row: Instrument) -> Instrument | None:
        """同一产品的另一种形态；`row` 本身是其中一种形态时返回另一侧，缺则 `None`。

        一个产品在库里可能有多行现货（不同报价，例如 `XAAPL-USDT` 与 `XAAPL-USDC`），
        因此配对按形态选、不按 `symbol` 选：现货行的对手腿永远是永续，永续行的对手
        腿永远是现货。挑「另一条现货」会把两种形态说成同一个东西。
        """

        return self.swap if row.inst_type == SPOT else self.spot


def build_instrument(ref: InstrumentRef) -> Instrument:
    """把上游标的快照翻译成落库模型（纯映射，不碰数据库）。"""

    inst_type = ref.inst_type.strip().upper()
    if inst_type not in INST_TYPES:
        raise ValidationError(f"标的 {ref.inst_id} 的 instType 不支持:{ref.inst_type!r}")

    product_key = _product_key(ref, inst_type)
    return Instrument(
        symbol=ref.inst_id,
        inst_type=inst_type,
        product_key=product_key,
        asset_type=_asset_type(ref.inst_category),
        exchange=EXCHANGE,
        base_currency=product_key,
        quote_currency=_quote_currency(ref, inst_type),
        tick_size=ref.tick_size,
        lot_size=ref.lot_size,
        min_order_size=ref.min_size,
        listing_time=ref.list_time,
        trading_status=_trading_status(ref),
        data_start=_data_start(ref),
        ct_val=ref.ct_val,
        ct_mult=ref.ct_mult,
        ct_type=ref.ct_type or None,
        max_lever=ref.max_lever,
        settle_ccy=ref.settle_ccy or None,
    )


def _asset_type(inst_category: str) -> str:
    return _ASSET_TYPES.get(inst_category.strip(), UNKNOWN_ASSET_TYPE)


def _product_key(ref: InstrumentRef, inst_type: str) -> str:
    """同一产品的配对键。

    只有代币化股票（`instCategory == 3`）的现货带 `X` 标记，因此也只有这一类
    现货需要去掉它；加密资产的 `XRP`、`XLM` 去掉 X 会变成另一个不存在的东西。
    """

    if inst_type == SWAP:
        return _require(ref.ct_val_ccy, ref.inst_id, "ctValCcy")
    if ref.inst_category.strip() != TOKENIZED_EQUITY_CATEGORY:
        return _require(ref.base_ccy, ref.inst_id, "baseCcy")
    base_ccy = _require(ref.base_ccy, ref.inst_id, "baseCcy")
    if len(base_ccy) < 2 or not base_ccy.startswith("X"):
        raise ValidationError(f"代币化股票现货 {ref.inst_id} 的 baseCcy 缺少 X 标记:{base_ccy!r}")
    return base_ccy[1:]


def _quote_currency(ref: InstrumentRef, inst_type: str) -> str:
    if inst_type == SWAP:
        return _require(ref.settle_ccy, ref.inst_id, "settleCcy")
    return _require(ref.quote_ccy, ref.inst_id, "quoteCcy")


def _trading_status(ref: InstrumentRef) -> str:
    return _require(ref.state, ref.inst_id, "state")


def _data_start(ref: InstrumentRef) -> datetime | None:
    """行情从上市时刻开始有；还没上市的标的不给伪起点。"""

    if _trading_status(ref) == "preopen":
        return None
    return ref.list_time


def _require(value: str, inst_id: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ValidationError(f"标的 {inst_id} 缺少 {field}")
    return text
