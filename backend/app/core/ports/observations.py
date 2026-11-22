"""观测值协议：宏观与行情共用同一份 Provider 抽象。

与 `market_data.py` 的 `MarketDataPort` 同层：跨域协作靠这份契约，不靠具体厂商。

`Observation` 只带「这条事实本身就有」的字段。`trading_day`（归属交易日）与
`market_session`（交易时段）是派生值，由各域的 enrich 中间件按 `ts` 算出：它们是
**同一个 `ts` 的两种解释**，不该让每个 provider 各自复制一遍交易日历与时段规则，
否则两个源对同一时刻会给出不同的交易日。

`ts` 是 UTC epoch 秒整数，与 `candles.open_time` 同一套约定（`app.market.model` 的
`to_epoch` / `from_epoch`）：秒以下精度一律拒绝，避免同一分钟出现多个键。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

__all__ = ["Observation", "ObservationProvider"]


@dataclass(frozen=True, slots=True)
class Observation:
    """一条观测值：哪个序列、哪个时刻、哪个来源、值是多少、是否延迟。"""

    series_id: str
    ts: int
    value: Decimal
    provider: str
    is_delayed: bool


@runtime_checkable
class ObservationProvider(Protocol):
    """数据源实现：声明支持哪些序列，再按需取回观测值。

    `since` 是「只要不早于这个时刻的观测」，为 `None` 表示不设下界。实现必须按它
    过滤，而不是把整段历史都交出来——日更源的历史有上万行，调度器每分钟都全量写一遍
    是纯浪费。
    """

    name: str

    def supports(self, series: Sequence[str]) -> bool: ...

    def fetch(self, series: Sequence[str], since: datetime | None) -> list[Observation]: ...
