"""`candles` 表里美股 K 线的读回：每个标的的最近一根、指定来源与周期。

写路径不在这里（`upsert_candles` 已按唯一键幂等写入），本模块只负责「读最新一根」：

- 必须同时按 `bar` 与 `source` 过滤。换过 provider 后旧来源的行还在表里，把两个来源
  的行混在一起读出来的「最新价」既不是这个源的价格，也不是那个源的。
- 一个标的只返回一行（`DISTINCT ON`）：首页要的是最后成交的那一根，不是一段历史。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.core import Bar
from app.db import session_scope
from app.market import Candle, from_epoch, to_epoch

__all__ = ["StoredBar", "existing_keys", "latest_bars"]


@dataclass(frozen=True, slots=True)
class StoredBar:
    """库里某个标的最近一根已收盘 K 线里，界面需要的那几列。"""

    symbol: str
    bar: str
    source: str
    open_time: datetime
    close: Decimal
    market_session: str


def latest_bars(
    symbols: Sequence[str],
    *,
    bar: str,
    source: str,
) -> dict[str, StoredBar]:
    """每个标的在该「周期 + 来源」下的最近一根 K 线；没有数据的标的不出现。"""

    wanted = list(dict.fromkeys(symbols))
    if not wanted:
        return {}
    statement = (
        select(Candle)
        .where(
            Candle.symbol.in_(wanted),
            Candle.bar == bar,
            Candle.source == source,
        )
        .distinct(Candle.symbol)
        .order_by(Candle.symbol, Candle.open_time.desc())
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
    return {
        row.symbol: StoredBar(
            symbol=row.symbol,
            bar=row.bar,
            source=row.source,
            open_time=from_epoch(row.open_time),
            close=row.close,
            market_session=row.market_session,
        )
        for row in rows
    }


def existing_keys(bars: Sequence[Bar]) -> set[tuple[str, str, int, str]]:
    """这批 K 线里**已经落库**的主键；用来区分「本次新写入」与「重复抓到」。

    抓取窗口覆盖一整个交易日，绝大多数行每分钟都会被重新抓到一次：事件总线只该收到
    真正新写进来的那几根，否则同一根 K 线会被反复当作「刚收盘」发布。
    """

    grouped: dict[tuple[str, str, str], list[int]] = {}
    for bar in bars:
        key = (bar.inst_id, bar.timeframe.value, bar.source)
        grouped.setdefault(key, []).append(to_epoch(bar.open_time))
    found: set[tuple[str, str, int, str]] = set()
    if not grouped:
        return found
    with session_scope() as session:
        for (symbol, bar_name, source), open_times in grouped.items():
            statement = select(Candle.open_time).where(
                Candle.symbol == symbol,
                Candle.bar == bar_name,
                Candle.source == source,
                Candle.open_time.in_(open_times),
            )
            found.update(
                (symbol, bar_name, int(stamp), source) for stamp in session.scalars(statement)
            )
    return found
