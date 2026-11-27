"""价格相关标的的 K 线刷新：过期就交给已有的按需同步队列补一次。

不新增定时器：调用点就在 `app.jobs.market_data` 已经存在的调度轮次里，与大盘提醒同一种
写法。真正的取数、去重、并发与失败流水仍由 `OnDemandSyncScheduler` / `run_candle_sync`
负责，本模块只回答一个问题：谁的价格该刷新了。

## 刷新范围

有持仓的标的 ∪ 自选。这两类是持仓卡片、自选指标与市场广度实际读到的序列；长尾标的
仍然只在用户点开时才同步——给整个标的表做定时全量同步会把上游额度花在没人看的标的上。

## 为什么不会把上游打满

三道闸门叠在一起：

1. 只看「已经过期」的周期：最新一根 K 线还没到下一个周期边界时不提交；
2. 同一个 `(标的, 周期)` 每个周期最多尝试一次（`attempted`），失败也等下一个周期，
   不让一次上游故障变成每分钟一条失败流水；
3. `OnDemandSyncScheduler` 自己按 `(标的, 周期)` 去重并限制并发。

刷新窗口按缺口算，不按设置里的全量回看窗口算：补一根日线只取几天，不重新拉 400 天。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import Clock, SystemClock
from app.instrument import get_instruments
from app.jobs.on_demand import DEFAULT_DAYS_BY_BAR, OnDemandSyncScheduler
from app.market import latest_open_times
from app.positions import held_instruments
from app.shared import bar_seconds, normalize_bar
from app.watchlist import tracked_instruments

__all__ = [
    "MAX_REFRESH_DAYS",
    "REFRESH_BARS",
    "SETTLE_GRACE",
    "CandleRefreshTarget",
    "refresh_due",
    "run_candle_refresh",
]

logger = logging.getLogger(__name__)

#: 需要维持新鲜的周期。`1d` 撑起持仓卡片的标记价、自选指标与市场广度，`1h` 撑起日内
#: 分析；比这两档更细的周期只在用户点开标的时同步，定时刷新不替它跑。
REFRESH_BARS: tuple[str, ...] = ("1d", "1h")

#: 已经有一根 K 线时，单次刷新最多回看的整天数。更长的缺口靠用户点开标的做全量同步，
#: 定时刷新只保证「最近一段可用」，不让一次历史缺口把每轮都要下载的窗口放大。
MAX_REFRESH_DAYS = 30

#: 收盘之后还要留一点时间给上游结算：卡着周期边界去取，常常还拿不到刚收盘的那根。
SETTLE_GRACE = timedelta(minutes=1)

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True, slots=True)
class CandleRefreshTarget:
    """一次要补的 `(标的, 周期)`，以及要回看多少天。"""

    symbol: str
    bar: str
    days: int


#: 同一 `(标的, 周期)` 上一次尝试的时刻。模块级一份即可：只有一个调度线程写它。
_ATTEMPTED: dict[tuple[str, str], datetime] = {}


def refresh_due(latest: datetime | None, now: datetime, bar: str) -> int | None:
    """这个周期现在该刷新吗？返回刷新时要回看的天数，不该刷时返回 `None`。

    三种情况：

    - 一根 K 线都没有：按该周期的默认回看窗口补一次（`1d` 400 天、`1h` 30 天）；
    - 下一根还不可能收盘：返回 `None`；
    - 其余：按缺口天数回看，至少 1 天，最多 `MAX_REFRESH_DAYS` 天。

    「下一根还不可能收盘」按**两个**周期算，不是一个：库里最后一根 K 线的开盘时刻是
    `L`，紧接的那根从 `L + 一个周期` 开始、要到 `L + 两个周期` 才收盘，在它收盘之前
    上游拿不到任何更新的已收盘行。只等一个周期会在每根 bar 收盘前多打一次上游，且只能
    把同一根重新下载一遍。

    判定只用「这根 K 线什么时候收盘」与当前时刻，不看标的类别、来源或资产类型：停更
    的原因不重要，重要的是这个价多久没动了。
    """

    canonical = normalize_bar(bar)
    if latest is None:
        return DEFAULT_DAYS_BY_BAR.get(canonical, 1)
    if latest.tzinfo is None or now.tzinfo is None:
        raise ValueError("latest/now must be timezone-aware")

    if now < latest + 2 * _bar_span(canonical) + SETTLE_GRACE:
        return None
    gap_seconds = int((now - latest).total_seconds())
    return max(1, min(-(-gap_seconds // _SECONDS_PER_DAY) + 1, MAX_REFRESH_DAYS))


def run_candle_refresh(
    scheduler: OnDemandSyncScheduler | None,
    *,
    clock: Clock | None = None,
    attempted: MutableMapping[tuple[str, str], datetime] | None = None,
) -> tuple[CandleRefreshTarget, ...]:
    """把过期周期提交给按需同步队列，返回本次真正提交的目标。

    `attempted` 是「上一次尝试的时刻」表，默认用模块级的一份：同一进程里只有一条调度
    线程，不需要加锁。测试传入自己的映射即可得到确定结果。
    """

    if scheduler is None:
        # 没有队列就是没有同步能力（测试装配或装配失败）；刷新不成立，也不报错。
        return ()
    moment = (clock or SystemClock()).now()
    memory = _ATTEMPTED if attempted is None else attempted
    targets = _due_targets(now=moment, attempted=memory)
    submitted: list[CandleRefreshTarget] = []
    for target in targets:
        # 先记尝试时刻再提交：提交成功但随后失败时，也要等下一个周期才重试。
        memory[(target.symbol, target.bar)] = moment
        try:
            scheduler.submit(target.symbol, target.bar, target.days)
        except Exception:
            logger.exception("K 线刷新提交失败: inst_id=%s bar=%s", target.symbol, target.bar)
            continue
        submitted.append(target)
    if submitted:
        logger.info(
            "K 线刷新已提交 %d 个周期: %s",
            len(submitted),
            ", ".join(f"{item.symbol}/{item.bar}={item.days}天" for item in submitted),
        )
    return tuple(submitted)


def _due_targets(
    *,
    now: datetime,
    attempted: Mapping[tuple[str, str], datetime],
) -> tuple[CandleRefreshTarget, ...]:
    """读出价格相关标的的最新 K 线时刻，挑出该刷新的周期。

    时刻按 `(标的, 周期)` 一批取回，不按标的发语句；这里只关心时刻，来源与价格留给
    卡片与指标各自的口径。
    """

    symbols = _price_symbols()
    if not symbols:
        return ()
    latest = latest_open_times(symbols, bars=REFRESH_BARS)
    targets: list[CandleRefreshTarget] = []
    for symbol in symbols:
        for bar in REFRESH_BARS:
            days = refresh_due(latest.get((symbol, bar)), now, bar)
            if days is None:
                continue
            previous = attempted.get((symbol, bar))
            if previous is not None and now - previous < _bar_span(bar):
                continue
            targets.append(CandleRefreshTarget(symbol=symbol, bar=bar, days=days))
    return tuple(targets)


def _price_symbols() -> tuple[str, ...]:
    """价格还在被人用的标的：有持仓的 ∪ 自选，去重后按标识固定顺序。

    只保留标的表里登记过的行：没同步过的标识连类别都不知道，交给标的同步去处理，不要
    每轮都在这里造一条必然失败的同步。
    """

    wanted = (*held_instruments(), *(row.symbol for row in tracked_instruments()))
    known = get_instruments(wanted)
    return tuple(sorted(symbol for symbol in set(wanted) if symbol in known))


def _bar_span(bar: str) -> timedelta:
    """一个周期的长度；过期判定与尝试记忆共用同一份换算。"""

    return timedelta(seconds=bar_seconds(bar))
