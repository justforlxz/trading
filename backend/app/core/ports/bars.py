"""K 线来源协议：第三方的行情实现共用同一份抽象。

与 `observations.py` 的 `ObservationProvider` 同一层、同一形状：一个实现一个名字，
`supports` 声明它能服务哪些标的，`fetch` 取回一个时间窗口内**已收盘**的 K 线。

两份协议不合并：观测值是一行一个标量（宏观的 10Y、VIX），K 线是完整 OHLCV 且带
周期，`candles` 表的主键里就有周期。把两者塞进同一个协议会让宏观实现返回一份它
不需要的字段。

`fetch` 是同步的：唯一调用方是进程内的调度线程（`app/jobs/market_data.py`），
为了一个端口把整条链改成异步会凭空引入事件循环。上游故障收敛成 `UpstreamError`
的子类，不往上抛裸的传输层异常。

`bar` 声明这个实现**实际提供**的周期（Yahoo 免费源给 1 分钟，Stooq 只给日线）：
周期不是调用方想改就能改的，配置切到哪个实现就落哪个周期，不把日线数据冒充分钟级。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.core.types import Bar

__all__ = ["BarProvider"]


@runtime_checkable
class BarProvider(Protocol):
    """行情来源实现：按标的清单取回 `[start, end)` 内已收盘的 K 线。

    `name` 会写进 `candles.source`，是主键的一部分——不知道从哪个源来的价格不能当
    行情用，因此实现必须如实填自己的注册名。
    """

    name: str
    bar: str

    def supports(self, symbols: Sequence[str]) -> bool:
        """这批标的是否都能由本实现服务；不能时实现方应抛 `UpstreamError`。"""

        ...

    def fetch(self, symbols: Sequence[str], start: datetime, end: datetime) -> list[Bar]:
        """取回窗口内的 K 线（升序）；只返回已收盘的那些。"""

        ...
