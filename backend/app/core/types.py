"""跨模块值对象。

全部 frozen：跨层传递时只读，任何「更新」都产生新实例，调用方不必猜透传过程
有没有被就地改过。值对象里不允许出现 session / db / client 之类的基础设施引用，
那会把数据层的生命周期漏进业务层。

价格与数量一律用 `Decimal`，时间一律是带时区的 `datetime`（UTC）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from app.core.errors import ValidationError

__all__ = ["Bar", "InstrumentRef", "Money", "OrderIntent", "Signal", "Timeframe"]

# 规范周期 → 秒数。上游的 bar 写法映射只发生在交易所适配层。
_BAR_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

_SIGNAL_SIDES = frozenset({"long", "short", "flat"})
_ORDER_SIDES = frozenset({"buy", "sell"})
_ORDER_TYPES = frozenset({"market", "limit"})


@dataclass(frozen=True, slots=True)
class Timeframe:
    """规范周期。

    `value` 只能是六个内部枚举之一，`seconds` 必须与之一致；两者都在构造时校验，
    因此不存在「1h 却按 300 秒处理」的实例。

    这是周期的单一真源：上层需要周期表时从 `ALL` 派生，不要再写第二份。
    """

    value: str
    seconds: int

    ALL: ClassVar[tuple[Timeframe, ...]]

    def __post_init__(self) -> None:
        expected = _BAR_SECONDS.get(self.value)
        if expected is None:
            raise ValidationError(f"不支持的周期:{self.value!r}")
        if self.seconds != expected:
            raise ValidationError(f"周期 {self.value} 的秒数应为 {expected}, 实际 {self.seconds}")

    @classmethod
    def parse(cls, raw: str) -> Timeframe:
        """按规范写法构造；上游别名只在适配层转换，这里不做归一化。"""

        seconds = _BAR_SECONDS.get(raw)
        if seconds is None:
            supported = ", ".join(_BAR_SECONDS)
            raise ValidationError(f"不支持的周期 {raw!r}; 支持: {supported}")
        return cls(raw, seconds)


Timeframe.ALL = tuple(Timeframe(value, seconds) for value, seconds in _BAR_SECONDS.items())


@dataclass(frozen=True, slots=True)
class Money:
    """金额：`amount` 必须是 `Decimal`，`currency` 用规范写法（如 `USDT`）。"""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise ValidationError(f"金额必须是 Decimal, 实际 {type(self.amount).__name__}")
        if not self.currency:
            raise ValidationError("金额的币种不能为空")


@dataclass(frozen=True, slots=True)
class Bar:
    """一根 K 线。

    `confirm` 为 False 表示该周期尚未收盘（仍会变动）；`source` 标明数据来源，
    是持久化的主键之一，空来源没有意义——不知道从哪来的价格不能当行情用。

    `market_session` 是这根 K 线所属的资产时段（`app/market/session.py` 的四个取值），
    空字符串表示来源没有声明；时段语义属于 market 域，core 只带值不解释。
    """

    inst_id: str
    timeframe: Timeframe
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirm: bool
    source: str
    market_session: str = ""

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None:
            raise ValidationError("K 线的 open_time 必须带时区")
        if not self.source.strip():
            raise ValidationError("K 线缺少数据来源")


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    """上游下发的标的静态快照：身份 + 交易所侧的交易规则。

    这是端口的返回值，不是持久化模型——落库的 `Instrument` 属于 instrument 域。

    `inst_category` 保留上游分类码（OKX 的 `instCategory`），资产类型的语义映射由
    instrument 域完成。三个精度字段（`tick_size`/`lot_size`/`min_size`）可能为
    None：尚未开盘的标的（`state` 为 `preopen`）上游并不下发，此时保留标的本身、
    把精度标为「未知」，而不是伪造数值或丢弃整条记录。

    永续专属字段只在 `inst_type` 为 `SWAP` 时有值：`ct_val_ccy` 是合约标的币种
    （现货侧对应 `base_ccy`），`settle_ccy` 是结算币种，其余是合约乘数与杠杆规则。
    同一产品的现货与永续靠这些字段对齐，不靠拆 `instId` 字符串。
    """

    inst_id: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    state: str
    inst_category: str = ""
    tick_size: Decimal | None = None
    lot_size: Decimal | None = None
    min_size: Decimal | None = None
    list_time: datetime | None = None
    ct_val_ccy: str = ""
    settle_ccy: str = ""
    ct_val: Decimal | None = None
    ct_mult: Decimal | None = None
    ct_type: str = ""
    max_lever: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Signal:
    """策略给出的一次方向判断。

    `strength` 是 0..1 的置信强度，不是仓位；下单量由仓位与风控决定。
    `ts` 是产生信号的时刻，必须来自注入的时钟，而不是直接读系统时间。
    """

    inst_id: str
    side: str
    strength: float
    ts: datetime
    reason: str = ""

    def __post_init__(self) -> None:
        if self.side not in _SIGNAL_SIDES:
            raise ValidationError(f"信号方向必须是 {sorted(_SIGNAL_SIDES)}, 实际 {self.side!r}")
        if not 0.0 <= self.strength <= 1.0:
            raise ValidationError(f"信号强度必须在 0..1 之间, 实际 {self.strength}")
        if self.ts.tzinfo is None:
            raise ValidationError("信号的 ts 必须带时区")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """下单意图：风控与执行之间传递的目标，不是已存在的订单。

    限价单必须给出 `price`，市价单不得给出 `price`——两者互斥，否则执行层要猜
    「以哪个为准」。`client_order_id` 供幂等使用，留空表示调用方不要求去重。
    """

    inst_id: str
    side: str
    qty: Decimal
    order_type: str
    price: Decimal | None = None
    client_order_id: str = ""

    def __post_init__(self) -> None:
        if self.side not in _ORDER_SIDES:
            raise ValidationError(f"下单方向必须是 {sorted(_ORDER_SIDES)}, 实际 {self.side!r}")
        if self.order_type not in _ORDER_TYPES:
            raise ValidationError(
                f"订单类型必须是 {sorted(_ORDER_TYPES)}, 实际 {self.order_type!r}"
            )
        if self.qty <= 0:
            raise ValidationError(f"下单数量必须为正, 实际 {self.qty}")
        if self.order_type == "limit" and self.price is None:
            raise ValidationError("限价单必须给出 price")
        if self.order_type == "market" and self.price is not None:
            raise ValidationError("市价单不能给出 price")
