"""行情端口。

所有行情来源（OKX 适配器、回放数据、未来的聚合 provider）都实现同一组签名，业务
模块只认这个协议，不感知上游是哪个交易所、走 HTTP 还是读本地库。

实现约定：

- K 线按 `open_time` 升序返回；
- 周期一律是规范 `Timeframe`，上游写法映射留在适配层；
- 标的类别（`SPOT` / `SWAP`）由调用方以 `inst_type` 给出：上游标的与 K 线接口一次
  只服务一类，适配层不从 `inst_id` 拆字符串推断；
- 成交量一律是标的币数量，取列口径按 `inst_type` 在适配层决定；
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
    """最新行情快照（价格与 24 小时成交量）。`volume_24h` 恒为标的币数量。"""

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

    类别词表由实现方掌握：调用方给出未登记的 `inst_type` 时，实现方必须在发出任何
    请求前抛 `ValidationError`，不得静默返回空结果，也不得退回另一类的口径。
    """

    def instruments(self, inst_type: str) -> list[InstrumentRef]:
        """返回某一类别（`SPOT` / `SWAP`）的全部标的静态快照。"""

        raise NotImplementedError

    def candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        limit: int = 100,
    ) -> list[Bar]:
        """返回最近 `limit` 根 K 线（升序）；`inst_type` 决定成交量取列口径。"""

        raise NotImplementedError

    def history_candles(
        self,
        inst_id: str,
        timeframe: Timeframe,
        *,
        inst_type: str,
        after: datetime | None = None,
        limit: int = 100,
    ) -> list[Bar]:
        """返回历史 K 线（升序）；`after` 为分页游标，取更早的一段。"""

        raise NotImplementedError

    def ticker(self, inst_id: str, *, inst_type: str) -> Ticker:
        """返回最新行情快照；`volume_24h` 按 `inst_type` 取标的币数量。"""

        raise NotImplementedError

    def close(self) -> None:
        """释放底层连接资源。"""

        raise NotImplementedError
