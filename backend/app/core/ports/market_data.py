"""行情端口。

所有行情来源（OKX 适配器、回放数据、未来的聚合 provider）都实现同一组签名，业务
模块只认这个协议，不感知上游是哪个交易所、走 HTTP 还是读本地库。

实现约定：

- K 线按 `open_time` 升序返回；
- 周期一律是规范 `Timeframe`，上游写法映射留在适配层；
- 上游故障收敛成 `UpstreamError` 的子类，不往上抛裸的传输层异常。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.core.types import Bar, InstrumentRef, Timeframe

__all__ = ["MarketDataPort", "Ticker"]


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

    方法体一律 `raise NotImplementedError`：继承本协议却不实现某个方法是装配错误，
    应该在第一次调用时立刻暴露，而不是返回 None 让错误流到下游。
    """

    def instruments(self) -> list[InstrumentRef]:
        """返回全部标的的静态快照。"""

        raise NotImplementedError

    def candles(self, inst_id: str, timeframe: Timeframe, *, limit: int = 100) -> list[Bar]:
        """返回最近 `limit` 根 K 线（升序）。"""

        raise NotImplementedError

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        """返回历史 K 线（升序）；`after` 为分页游标，取更早的一段。"""

        raise NotImplementedError

    def ticker(self, inst_id: str) -> Ticker:
        """返回最新行情快照。"""

        raise NotImplementedError

    def close(self) -> None:
        """释放底层连接资源。"""

        raise NotImplementedError
