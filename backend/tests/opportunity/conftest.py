"""机会发现域测试装配：临时 schema，以及「按有效来源写入日线」的夹具。

日线的来源不是随手写的：先用 `app.market` 的「资产时段 × 资产类别」规则算出该标的
在 `as_of` 那一刻的有效来源，再按那个来源写入，因此检测读到的正是它自己此刻该读的
那一条序列——用错的来源写进去，检测会读不到（这本身就是 T1.7 的口径）。

根 `conftest.py` 已把引擎指向本用例独有的 schema。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core import Bar, InstrumentRef, Timeframe
from app.db import init_db
from app.exchange.okx.instruments import parse_instruments
from app.instrument import Instrument, resolve_instrument, sync_instruments
from app.market import asset_session, primary_source, upsert_candles
from tests.factories.instruments import load_all_instruments

DAY = timedelta(days=1)

# 判定时刻：2026-11-10 是美股交易日，23:00 UTC 是美东 18:00（盘后）。
# 代币化股票在盘后读代理行情，加密资产始终读 OKX 行情，两类来源都被覆盖到。
AS_OF = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)


@pytest.fixture()
def opportunity_schema() -> None:
    """执行迁移建好表；schema 由根 conftest 隔离。

    只在真的读写机会表的用例里请求这一条：纯函数用例不需要库，也就不该为每次
    迁移付一遍启动成本。
    """

    init_db()


def seed_instruments(*refs: InstrumentRef) -> None:
    """按交换层的返回值写库，形状与生产同步路径完全一致。"""

    sync_instruments(list(refs))


def seed_all_class_instruments() -> None:
    """把 T1.10 的全类别夹具整份写进标的表（两类 `instType`、四类 `instCategory`）。

    市场驱动必须扫「全部可交易标的」，用这份夹具才能证明扫描范围真的覆盖两类，
    而不是只覆盖用例手工造的那几行。
    """

    sync_instruments(parse_instruments(load_all_instruments()))


def all_class_symbols(inst_type: str, count: int) -> list[str]:
    """全类别夹具里某个类别的前若干个加密资产 `USDT` 标的（类别 `1`，全天候 OKX 行情）。"""

    rows = [
        row
        for row in load_all_instruments()
        if row["instType"] == inst_type
        and row["state"] == "live"
        and row["instCategory"] == "1"
        and (inst_type == "SWAP" or row["quoteCcy"] == "USDT")
    ]
    symbols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = row.get("ctValCcy") or row.get("baseCcy")
        if key in seen:
            continue
        seen.add(key)
        symbols.append(row["instId"])
        if len(symbols) == count:
            break
    return symbols


def effective_source(inst_id: str, inst_type: str = "SPOT", *, as_of: datetime = AS_OF) -> str:
    """该标的在 `as_of` 的有效行情来源，与检测读库时用的是同一条规则。"""

    instrument = resolve_instrument(inst_id, inst_type)
    state = asset_session(instrument.asset_type, as_of, inst_type=instrument.inst_type)
    return primary_source(state, instrument.asset_type, instrument.inst_type)


def seed_daily(
    inst_id: str,
    closes: Sequence[str],
    *,
    inst_type: str = "SPOT",
    as_of: datetime = AS_OF,
    source: str | None = None,
) -> None:
    """写入连续日线（每天一根，最后一根落在 `as_of` 当天）。

    来源缺省取该标的在 `as_of` 的有效来源；显式给出时按给出的来源写入——用来构造
    「K 线存在另一个来源下」这种情形。
    """

    instrument: Instrument = resolve_instrument(inst_id, inst_type)
    if source is None:
        source = effective_source(inst_id, inst_type, as_of=as_of)
    opens = [as_of - DAY * (len(closes) - 1 - index) for index in range(len(closes))]
    upsert_candles(
        [
            Bar(
                inst_id=instrument.symbol,
                timeframe=Timeframe.parse("1d"),
                open_time=open_time,
                open=Decimal(close),
                high=Decimal(close),
                low=Decimal(close),
                close=Decimal(close),
                volume=Decimal("10"),
                confirm=True,
                source=source,
            )
            for open_time, close in zip(opens, closes, strict=True)
        ]
    )
