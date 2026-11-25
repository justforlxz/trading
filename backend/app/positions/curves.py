"""收益曲线与持仓盈亏曲线的读侧：只读已落库的快照，不插值、不画假线。

两条曲线的来源不同，不能互相代替：

- 权益曲线取 `account_snapshots.equity`（每分钟一条）；
- 持仓盈亏曲线取 `exchange_position_snapshots.upl`，是**该持仓的未实现盈亏序列**，
  不是价格 K 线。

区间覆盖不足时返回 `available=False`：一个月窗口只有十天数据，画出来是一条截断的
线，会让人以为那十天就是一个月。调用方据此显示「这段区间还没有数据」。

## 已知限制：抽稀在 Python 做

两个读函数都把窗口内的行整段取回来再抽稀。当前体量（每分钟一条、十天约三千行）
没有压力，`captured_at` 上也有索引（迁移 `0025`）。按现在的采集频率，一年窗口是
五十万行量级——到那时应该改成在 SQL 里按时间桶聚合（`DISTINCT ON` 或
`date_trunc` 分组取每个桶的最后一条），把返回行数压到几百。在那之前改是过早优化：
分桶会让「区间涨跌」与「首尾点」依赖桶边界，而这两项正是曲线的语义。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.positions.model import AccountSnapshotRow, ExchangePositionSnapshotRow

_HUNDRED = Decimal(100)

__all__ = [
    "CURVE_RANGES",
    "MAX_EQUITY_POINTS",
    "MAX_UPL_POINTS",
    "MIN_COVERAGE_RATIO",
    "CurvePoint",
    "EquityCurve",
    "equity_curve",
    "upl_curves",
]

#: 界面上的五个区间。月按 30 天、半年按 182 天、年按 365 天算。
CURVE_RANGES: Mapping[str, timedelta] = {
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
    "1m": timedelta(days=30),
    "6m": timedelta(days=182),
    "1y": timedelta(days=365),
}
#: 权益曲线最多给这么多点；前端按宽度画折线，再多也只是重复的像素。
MAX_EQUITY_POINTS = 120
#: 持仓卡片里的迷你曲线只有 132px 宽，24 个点足够看出形状。
MAX_UPL_POINTS = 24
#: 窗口被数据覆盖到这个比例才算「这段区间有数据」。十天数据撑一个月只有 33%，
#: 画出来是骗人的，因此判为数据不足。
MIN_COVERAGE_RATIO = 0.9


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """曲线上的一点；`at` 是快照时刻。"""

    at: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class EquityCurve:
    """一段区间内的权益曲线。

    `available=False` 时 `points` 为空，`first_snapshot_at` 给出库里最早一条快照的
    时刻，用来在界面上说明「快照自 … 起记录」。
    """

    range: str
    available: bool
    points: tuple[CurvePoint, ...]
    #: 区间涨跌百分比（首尾两点之差 ÷ 首点）；不足两点时为 `None`。
    #: 页面上的「+2.33%」直接用这个值——派生数字不在前端算。
    change_pct: Decimal | None
    first_snapshot_at: datetime | None
    last_snapshot_at: datetime | None


def equity_curve(range_key: str, *, now: datetime | None = None) -> EquityCurve:
    """最近一个区间内的权益曲线；覆盖不足时 `available=False` 且不给点。"""

    window = CURVE_RANGES[range_key]
    moment = now or datetime.now(UTC)
    start = moment - window
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(AccountSnapshotRow)
                .where(AccountSnapshotRow.captured_at >= start)
                .order_by(AccountSnapshotRow.captured_at)
            )
        )
        first = session.scalars(
            select(AccountSnapshotRow.captured_at).order_by(AccountSnapshotRow.captured_at).limit(1)
        ).first()
    points = tuple(CurvePoint(row.captured_at, row.equity) for row in rows)
    covered = _covered(points, window)
    available = covered and len(points) >= 2
    return EquityCurve(
        range=range_key,
        available=available,
        points=_downsample(points, MAX_EQUITY_POINTS) if available else (),
        change_pct=_change_pct(points) if available else None,
        first_snapshot_at=first,
        last_snapshot_at=points[-1].at if points else None,
    )


def upl_curves(range_key: str, *, now: datetime | None = None) -> dict[str, tuple[CurvePoint, ...]]:
    """每条持仓的未实现盈亏序列；`pos_id` → 点。

    没有 `upl` 的快照不产生点：那条快照没读到盈亏，补 0 会画出一条假的水平线。
    """

    window = CURVE_RANGES[range_key]
    moment = now or datetime.now(UTC)
    start = moment - window
    with session_scope() as session:
        rows = session.execute(
            select(
                ExchangePositionSnapshotRow.pos_id,
                ExchangePositionSnapshotRow.captured_at,
                ExchangePositionSnapshotRow.upl,
            )
            .where(
                ExchangePositionSnapshotRow.captured_at >= start,
                ExchangePositionSnapshotRow.upl.is_not(None),
            )
            .order_by(ExchangePositionSnapshotRow.captured_at)
        ).all()
    grouped: dict[str, list[CurvePoint]] = {}
    for pos_id, captured_at, upl in rows:
        grouped.setdefault(pos_id, []).append(CurvePoint(captured_at, upl))
    return {
        pos_id: _downsample(points, MAX_UPL_POINTS)
        for pos_id, points in grouped.items()
        if len(points) >= 2
    }


def _change_pct(points: Sequence[CurvePoint]) -> Decimal | None:
    """区间涨跌：`(末 - 首) / 首 × 100`；首点为 0 时没有意义，返回 `None`。"""

    if len(points) < 2:
        return None
    first = points[0].value
    if first == 0:
        return None
    return (points[-1].value - first) / first * _HUNDRED


def _covered(points: Sequence[CurvePoint], window: timedelta) -> bool:
    """首尾跨度达到窗口的比例才算这段区间有数据。"""

    if len(points) < 2:
        return False
    return (points[-1].at - points[0].at) >= window * MIN_COVERAGE_RATIO


def _downsample(points: Sequence[CurvePoint], limit: int) -> tuple[CurvePoint, ...]:
    """等间隔抽稀，首尾一定保留，绝不改变数值。"""

    if len(points) <= limit:
        return tuple(points)
    step = (len(points) - 1) / (limit - 1)
    picked = {round(index * step) for index in range(limit)}
    return tuple(points[index] for index in sorted(picked))
