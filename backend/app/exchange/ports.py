"""行情端口与中立数据结构。

这是业务模块访问行情的唯一入口：上层依赖 `MarketDataPort` 与这里的数据类，
不感知上游是哪个交易所、走 HTTP 还是别的传输。

数据类统一使用 `Decimal` 承载价格与数量、`datetime`（UTC、带时区）承载时间，
避免上游字符串精度在中间层被浮点化。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["Candle", "InstrumentInfo", "MarketDataPort", "Ticker", "utc_from_millis"]


def utc_from_millis(value: str | int) -> datetime:
    """毫秒时间戳 → 带时区的 UTC 时间。

    上游普遍用毫秒时间戳字符串表示时间，这里统一在边界上转换，往内一律是
    带时区的 `datetime`。
    """

    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    """单个交易标的的静态元数据。

    `inst_category` 保留上游的标的分类码（OKX 的 `instCategory`），它区分
    代币化股票、加密货币等资产类型，由上层做语义映射。

    三个交易精度字段（`tick_size`/`lot_size`/`min_size`）可能为 None：尚未开盘
    的标的（`state` 为 `preopen`）上游并不下发这些参数，此时保留标的本身、把
    精度标为「未知」，而不是伪造一个数值或丢弃整条记录。
    """

    inst_id: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    state: str
    inst_category: str
    tick_size: Decimal | None
    lot_size: Decimal | None
    min_size: Decimal | None
    list_time: datetime | None


@dataclass(frozen=True, slots=True)
class Candle:
    """一根 K 线。

    `confirm` 为 False 表示该周期尚未收盘（仍会变动）；`source` 标明数据来源，
    是持久化主键的一部分。
    """

    inst_id: str
    bar: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    confirm: bool
    source: str


@dataclass(frozen=True, slots=True)
class Ticker:
    """最新行情快照（价格与 24 小时成交量）。"""

    inst_id: str
    last: Decimal
    bid: Decimal
    ask: Decimal
    volume_24h: Decimal
    ts: datetime


@runtime_checkable
class MarketDataPort(Protocol):
    """行情端口：业务模块只依赖这些方法签名。

    实现必须返回按时间升序排列的 K 线，并把所有上游故障收敛成
    `ExchangeError`。
    """

    def instruments(self) -> list[InstrumentInfo]:
        """返回现货标的元数据列表。"""

    def candles(self, inst_id: str, bar: str, *, limit: int = 100) -> list[Candle]:
        """返回最近 `limit` 根 K 线（升序）。"""

    def history_candles(
        self,
        inst_id: str,
        bar: str,
        *,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Candle]:
        """返回历史 K 线（升序）；`after` 为分页游标，取更早的一段。"""

    def ticker(self, inst_id: str) -> Ticker:
        """返回最新行情快照。"""

    def close(self) -> None:
        """释放底层连接资源。"""
