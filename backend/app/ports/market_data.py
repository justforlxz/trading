"""行情端口的数据传输对象与协议。

DTO 是「已归一化」的数据：bar 用小写内部枚举、时间为 UTC aware datetime、
价格数量为 Decimal。原始响应（OKX JSON、Yahoo JSON）只允许出现在 adapters 内部，
不外泄到业务层与 API（api-contract §1.3「不透传上游原始结构」）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class InstrumentRow:
    """一个可交易标的（OKX SWAP 合约）的归一化字段。"""

    inst_id: str
    inst_family: str
    uly: str
    inst_category: int
    asset_class: str
    exchange: str | None
    ct_val: Decimal
    ct_val_ccy: str
    lot_sz: Decimal
    min_sz: Decimal
    tick_sz: Decimal
    lever: Decimal
    state: str
    rule_type: str
    list_time: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CandleRow:
    """OKX 永续合约的归一化 K 线（`confirm=false` 表示未完成 bar）。"""

    inst_id: str
    bar: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    vol: Decimal
    vol_ccy: Decimal
    vol_ccy_quote: Decimal
    confirm: bool
    source: str


@dataclass(frozen=True, slots=True)
class EquityCandleRow:
    """真实美股 K 线（日线或分钟线），`session` 标注所属交易时段。"""

    symbol: str
    interval: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    session: str
    source: str


@dataclass(frozen=True, slots=True)
class EquityQuote:
    """真实美股最新价（用于与 OKX 合约价做基差对照，不作为交易价格）。"""

    symbol: str
    price: Decimal
    ts: datetime
    source: str


@dataclass(frozen=True, slots=True)
class BasisRow:
    """OKX 合约价与真实美股价的基差快照。"""

    inst_id: str
    symbol: str
    ts: datetime
    okx_price: Decimal
    equity_price: Decimal
    basis_bps: Decimal


class InstrumentSource(Protocol):
    """标的清单来源（OKX `GET /api/v5/public/instruments`）。"""

    async def fetch_instruments(self) -> list[InstrumentRow]: ...


class CandleSource(Protocol):
    """合约 K 线来源：增量（candles）与历史回补（history-candles）。"""

    async def fetch_candles(self, inst_id: str, bar: str, limit: int = 300) -> list[CandleRow]: ...

    async def fetch_history(
        self,
        inst_id: str,
        bar: str,
        start: datetime,
        end: datetime,
        page_limit: int = 100,
    ) -> list[CandleRow]: ...


class EquitySource(Protocol):
    """真实美股行情来源；`name` 落库到 equity_asset.source_name 以便追溯。"""

    name: str

    async def fetch_daily(self, symbol: str, lookback_days: int = 10) -> list[EquityCandleRow]: ...

    async def fetch_quote(self, symbol: str) -> EquityQuote | None: ...


class CandleStore(Protocol):
    """K 线落库端口：幂等 upsert，返回写入（含更新）行数。"""

    async def upsert_candles(self, instrument_id: int, rows: list[CandleRow]) -> int: ...
