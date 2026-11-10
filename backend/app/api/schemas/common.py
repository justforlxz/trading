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
    "QtyUnit",
    "SiblingQuote",
    "Signal",
    "SignalAction",
    "StrategyStatus",
    "TargetLeg",
    "TargetPortfolio",
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
# 组件层判断：单个基础组件对某个标的看多、看空还是不动。它不表达仓位，也不表达
# 组合——「怎么做、做多少、做哪几条腿」由下面的 `TargetPortfolio` 承载。
SignalAction = Literal["BUY", "SELL", "HOLD"]
PositionSide = Literal["long", "short"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "open", "partially_filled", "filled", "cancelled", "rejected"]
ExecutionMode = Literal["manual", "paper", "live"]
ExecutionModel = Literal["next_open", "next_close"]
# 策略生命周期（`docs/prd/v2.md` §三.5 的八阶段）：机会发现 → 策略生成（草稿）→
# 人工审核 → 历史回测 → 量化验证 → 模拟交易 → 实盘授权 → 实盘运行。
# `rejected` 是生命周期之外的驳回分支：人工审核或量化验证不通过时落到这里，
# 只能回到 `strategy_generation` 重新提交（见 `docs/prd/decisions.md` D7）。
# 名称必须与 `decisions.md` D7 逐字一致，由 `tests/api/test_contract_schema.py` 把关。
StrategyStatus = Literal[
    "opportunity_discovery",
    "strategy_generation",
    "pending_review",
    "backtested",
    "validated",
    "paper_trading",
    "live_authorized",
    "live_running",
    "rejected",
]
# 目标组合的每条腿以什么计价：SPOT 按标的币数量，SWAP 按合约张数。
QtyUnit = Literal["base", "contract"]
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


class TargetLeg(BaseModel):
    """目标组合的一条腿：某个标的、某个方向、某个目标权重。

    `target_weight` 是权重（占组合资金的比例，正数表示该腿的大小），方向单独由
    `direction` 表达——不用权重符号再编码一次方向。

    `qty` 与 `unit` 是**服务端换算出的**下单数量：`SPOT` 按标的币数量（`base`），
    `SWAP` 按合约张数（`contract`），换算依赖价格、合约面值与精度，前端不做这类
    派生计算（`AGENTS.md` §6）。因此请求里可以不带这两个字段，由服务端在生成目标
    组合时填入；读到 `null` 表示这一步尚未换算。
    """

    inst_id: str
    inst_type: InstType
    direction: PositionSide
    target_weight: DecimalString
    qty: DecimalString | None = None
    unit: QtyUnit | None = None


class TargetPortfolio(BaseModel):
    """目标组合：多腿、多空并存，`net_exposure` 是多头权重之和减空头权重之和。"""

    legs: list[TargetLeg]
    net_exposure: DecimalString
