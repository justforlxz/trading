"""跨域共用的 API 契约类型。

这里只定形状与校验，不含任何业务逻辑。两条全局约定来自 `AGENTS.md`：

- 金额、价格、比率一律以字符串承载十进制数（`Decimal` 不落 JSON 浮点）。
- 时间一律 ISO-8601 UTC 带 `Z` 后缀。

因此本模块只发布 `DecimalString` / `UtcDatetime` 两个别名与跨域实体，
各域模型不直接暴露裸 `float` / `datetime`。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, PlainSerializer, StringConstraints

__all__ = [
    "AlertDirection",
    "AssetType",
    "Bar",
    "Candle",
    "DataSource",
    "DecimalString",
    "ExecutionMode",
    "ExecutionModel",
    "InstType",
    "InstrumentInfo",
    "InstrumentRef",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "ParamSpec",
    "ParamValue",
    "PositionSide",
    "SiblingQuote",
    "Signal",
    "SignalAction",
    "StrategyStatus",
    "TradingStatus",
    "UtcDatetime",
]

# 最多 20 位整数部分、12 位小数部分；允许负值（盈亏、价差）。
DECIMAL_PATTERN = r"^-?\d{1,20}(\.\d{1,12})?$"
DecimalString = Annotated[str, StringConstraints(pattern=DECIMAL_PATTERN)]


def _format_utc(value: datetime) -> str:
    """带时区时间 → `2026-11-10T08:00:00Z`。"""

    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


UtcDatetime = Annotated[
    AwareDatetime,
    PlainSerializer(_format_utc, return_type=str, when_used="json"),
]

# 与 `app/shared/timeframe.py` 的内部枚举一致；上游写法只允许出现在交易所适配层。
Bar = Literal["1m", "5m", "15m", "1h", "4h", "1d"]
InstType = Literal["SPOT", "SWAP"]
# 取值必须覆盖 `app.instrument` 的全部落库结果（含商品代币与未登记分类），
# 否则契约比领域层窄，遇到真实标的会在响应构造时校验失败。
AssetType = Literal["tokenized_equity", "crypto", "commodity_token", "unknown"]
# 行情来源标识与 `candles.source` 同值：同一产品的现货与永续是两行行情，必须能
# 分开取数。`okx` 仍在产出：K 线接口没有该标的行情时，路由会用标的自身的
# `exchange`（`app.instrument.model.EXCHANGE`，值为 `okx`）填 `data_source`
# （见 `app/api/routes/instruments.py` 的 `get_instrument_candles`），因此它也
# 必须留在契约里；同时它也是早期未区分形态的存量取值。
DataSource = Literal["okx", "okx_spot", "okx_swap", "us_equity_proxy"]
SignalAction = Literal["BUY", "SELL", "HOLD"]
PositionSide = Literal["long", "short"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "open", "partially_filled", "filled", "cancelled", "rejected"]
ExecutionMode = Literal["manual", "paper", "live"]
ExecutionModel = Literal["next_open", "next_close"]
StrategyStatus = Literal["draft", "enabled", "disabled"]
# 与上游 `state` 原文一一对应：交易所适配层不做词表翻译，契约也不能收窄。
TradingStatus = Literal["live", "suspend", "preopen", "test", "expired", "unknown"]
AlertDirection = Literal["above", "below"]

# 策略/指标参数值：JSON 标量，不做进一步的域内校验（各指标自证其参数）。
ParamValue = int | float | str | bool


class ParamSpec(BaseModel):
    """指标或策略的可配置参数定义。"""

    name: str
    title: str
    kind: Literal["int", "float", "bool", "string"]
    default: ParamValue
    minimum: float | None = None
    maximum: float | None = None


class InstrumentRef(BaseModel):
    """标的的最小可引用形状（列表、搜索结果用）。"""

    inst_id: str
    inst_type: InstType
    product_key: str
    asset_type: AssetType
    base_currency: str
    quote_currency: str


class InstrumentInfo(InstrumentRef):
    """标的静态元数据。SWAP 专属字段对 SPOT 为 null。"""

    tick_size: DecimalString | None = None
    lot_size: DecimalString | None = None
    min_order_size: DecimalString | None = None
    listing_time: UtcDatetime | None = None
    trading_status: TradingStatus = "unknown"
    max_leverage: DecimalString | None = None


class SiblingQuote(BaseModel):
    """同一 `product_key` 的另一形态报价。两形态不等价，界面必须同时展示价差。"""

    inst_id: str
    inst_type: InstType
    last_price: DecimalString
    price_spread_pct: DecimalString


class Candle(BaseModel):
    """一根 K 线。`is_closed=false` 表示未完成，`data_source` 区分真实/代理。"""

    open_time: UtcDatetime
    open: DecimalString
    high: DecimalString
    low: DecimalString
    close: DecimalString
    volume: DecimalString
    is_closed: bool
    data_source: DataSource


class Signal(BaseModel):
    """策略输出的标准化交易信号，策略本身不产生订单。"""

    model_config = ConfigDict(extra="forbid")

    signal_id: str
    strategy_instance_id: str
    inst_id: str
    inst_type: InstType
    action: SignalAction
    bar: Bar
    price: DecimalString
    reason: str
    generated_at: UtcDatetime
    target_weight: DecimalString | None = None
