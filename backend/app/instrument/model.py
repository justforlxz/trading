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

__all__ = ["Instrument", "InstrumentPair", "spot_currency", "unstorable_reason"]

EXCHANGE = "okx"

SPOT = "SPOT"
SWAP = "SWAP"
INST_TYPES = frozenset({SPOT, SWAP})

# OKX `instCategory`：3 = 代币化股票/ETF，1 = 加密资产，4 = 代币化商品。
TOKENIZED_EQUITY_CATEGORY = "3"
TOKENIZED_EQUITY = "tokenized_equity"
_ASSET_TYPES: dict[str, str] = {
    "3": TOKENIZED_EQUITY,
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
    """把上游标的快照翻译成落库模型（纯映射，不碰数据库）。

    上游还没下发币种的行无法确定产品键与报价币种，落库只能存半行：这里如实报错，
    由 `sync_instruments` 逐条跳过并记录原因，不让单行影响同批其余标的。
    """

    inst_type = _inst_type(ref)
    reason = unstorable_reason(ref)
    if reason is not None:
        raise ValidationError(f"标的 {ref.inst_id} {reason}")

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


def spot_currency(row: Instrument) -> str:
    """现货行的币种（上游 `baseCcy`），用来把账户余额的币种对回标的。

    `base_currency` 列存的是产品键（`AAPL`），而余额与下单用的是币种（`XAAPL`）。
    两者的换算只在标的模块定义一次：代币化股票的现货币种去掉 `X` 得到产品键，
    反推就补回 `X`；其余类别两者同值。
    """

    if row.inst_type != SPOT:
        raise ValidationError(f"标的 {row.symbol} 不是现货形态, 没有币种")
    if row.asset_type == TOKENIZED_EQUITY:
        return f"X{row.product_key}"
    return row.product_key


def unstorable_reason(ref: InstrumentRef) -> str | None:
    """这行还缺什么才能落库；字段齐全时返回 `None`。

    上游对还没开盘的标的（`state == "preopen"`）不下发币种：`baseCcy` 与 `quoteCcy`
    都是空串。这类行既说不清属于哪个产品，也说不清报价币种，落库只能存半行，因此
    由同步流程逐条跳过并记录原因，不让一行空币种把整批标的一起回滚。

    判定只看字段是否为空，不看 `state`：实测既有 `state == "live"` 而币种为空的行，
    也有 `state == "preopen"` 却已下发币种的行。
    """

    inst_type = _inst_type(ref)
    missing = [name for name, value in _currency_fields(ref, inst_type) if not value.strip()]
    if not missing:
        return None
    return f"上游未下发币种字段 {'/'.join(missing)}"


def _currency_fields(ref: InstrumentRef, inst_type: str) -> tuple[tuple[str, str], ...]:
    """这行依赖哪些币种字段：永续看合约标的币种与结算币种，现货看 base 与报价。"""

    if inst_type == SWAP:
        return (("ctValCcy", ref.ct_val_ccy), ("settleCcy", ref.settle_ccy))
    return (("baseCcy", ref.base_ccy), ("quoteCcy", ref.quote_ccy))


def _inst_type(ref: InstrumentRef) -> str:
    inst_type = ref.inst_type.strip().upper()
    if inst_type not in INST_TYPES:
        raise ValidationError(f"标的 {ref.inst_id} 的 instType 不支持:{ref.inst_type!r}")
    return inst_type


def _product_key(ref: InstrumentRef, inst_type: str) -> str:
    """同一产品的配对键。

    只有代币化股票（`instCategory == 3`）的现货带 `X` 标记，因此也只有这一类
    现货需要去掉它；加密资产的 `XRP`、`XLM` 去掉 X 会变成另一个不存在的东西。
    币种为空的行到不了这里：`unstorable_reason` 已经先一步把它们判为不可入库。
    """

    if inst_type == SWAP:
        return ref.ct_val_ccy.strip()
    base_ccy = ref.base_ccy.strip()
    if ref.inst_category.strip() != TOKENIZED_EQUITY_CATEGORY:
        return base_ccy
    if len(base_ccy) < 2 or not base_ccy.startswith("X"):
        raise ValidationError(f"代币化股票现货 {ref.inst_id} 的 baseCcy 缺少 X 标记:{base_ccy!r}")
    return base_ccy[1:]


def _quote_currency(ref: InstrumentRef, inst_type: str) -> str:
    if inst_type == SWAP:
        return ref.settle_ccy.strip()
    return ref.quote_ccy.strip()


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
