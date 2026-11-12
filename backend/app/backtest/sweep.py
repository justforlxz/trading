"""参数扫描：标的 × 参数笛卡尔积 × 训练/验证/样本外三段切分。

## 为什么分三段

同一段历史上把参数调到最好看，只能说明它拟合了这段历史。三段切分把「挑参数」和
「看效果」分开：训练段用来调参，验证段用来确认这个参数在另一段历史上是否还成立，
样本外段是最后一道闸门。三段必须**不重叠、无空隙、并集等于用户要回测的整段区间**，
否则「样本外」里会混进训练用过的 bar，过拟合就检不出来了。

## 为什么只给「行」，不给「最优」

扫描结果是一排可比较的行：每个（标的，参数组合）带着三个区间的指标。本模块不标
「最优参数」，也不按训练段的结果自动挑一个——那等于把过拟合写进结论。排序由
`batch.rank_rows` 负责，可以按任意一段的收益/回撤/Sharpe/PF 排，但排完仍然是并列展示。

## 职责边界

本模块是纯计算：不做 IO、不跑回测、不并发。展开出来的（标的，参数，区间）三元组由
装配层（`app.jobs`）交给队列执行，执行结果再装回 `SweepRow`。
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from app.backtest.batch import rank_rows
from app.core import ValidationError

__all__ = [
    "SPLIT_NAMES",
    "TEST_SEGMENT",
    "SplitWindow",
    "SweepCell",
    "SweepRow",
    "param_combinations",
    "rank_sweep",
    "split_window",
    "validate_splits",
]

#: 三段切分的固定名字与固定先后：训练 → 验证 → 样本外。
SPLIT_NAMES: tuple[str, ...] = ("train", "validation", "test")

#: 样本外段的名字。排序默认按这一段，因为它才是「没被挑参数用过」的那一段。
TEST_SEGMENT = "test"

DAY = timedelta(days=1)

#: 默认切分的三档比例，按「训练 60% / 验证 20% / 样本外 20%」分天。
_TRAIN_SHARE = 6
_VALIDATION_SHARE = 2
_SHARE_TOTAL = 10


@dataclass(frozen=True, slots=True)
class SplitWindow:
    """一段回测区间：名字取自 `SPLIT_NAMES`，日期是闭区间（两端都含）。"""

    name: str
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.name not in SPLIT_NAMES:
            raise ValidationError(f"未知区段名 {self.name!r}; 可选 {list(SPLIT_NAMES)}")
        for field_name in ("start_date", "end_date"):
            if not isinstance(getattr(self, field_name), date):
                raise ValidationError(f"区段 {self.name} 的 {field_name} 必须是日期")
        if self.start_date > self.end_date:
            raise ValidationError(
                f"区段 {self.name} 的起点 {self.start_date} 晚于终点 {self.end_date}"
            )


@dataclass(frozen=True, slots=True)
class SweepCell:
    """一次回测在一个区段上的结果：指标或可读错误，二者恰有其一。

    回测失败不抛给整批：一条腿的数据缺失不该让另外几个标的的结果消失，失败原因留在
    这一格里，由调用方原样展示。
    """

    segment: SplitWindow
    metrics: Mapping[str, Decimal] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.metrics is None and self.error is None:
            raise ValidationError(f"区段 {self.segment.name} 的回测结果必须带指标或错误之一")
        if self.metrics is not None and self.error is not None:
            raise ValidationError(f"区段 {self.segment.name} 的回测结果不能同时带指标和错误")


@dataclass(frozen=True, slots=True)
class SweepRow:
    """一个（标的，参数组合）的三段结果，行内各格按 `splits` 的顺序排列。"""

    inst_id: str
    params: Mapping[str, Any]
    cells: tuple[SweepCell, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.inst_id, str) or not self.inst_id.strip():
            raise ValidationError("扫描行的标的不能为空")
        if not isinstance(self.params, Mapping):
            raise ValidationError(f"标的 {self.inst_id} 的参数组合必须是映射")
        if not self.cells:
            raise ValidationError(f"标的 {self.inst_id} 的扫描行没有区段结果")
        names = [cell.segment.name for cell in self.cells]
        if len(set(names)) != len(names):
            raise ValidationError(f"标的 {self.inst_id} 的扫描行有重复区段: {names}")

    def cell(self, segment: str) -> SweepCell | None:
        """按区段名取这一行里的那一格；没有这段就返回 `None`。"""

        for candidate in self.cells:
            if candidate.segment.name == segment:
                return candidate
        return None

    def metrics_of(self, segment: str) -> Mapping[str, Decimal]:
        """取某一段的指标；这一段没有结果或回测失败时判错。"""

        found = self.cell(segment)
        if found is None:
            raise ValidationError(f"标的 {self.inst_id} 没有 {segment} 段的回测结果")
        if found.metrics is None:
            raise ValidationError(f"标的 {self.inst_id} 的 {segment} 段回测失败: {found.error}")
        return found.metrics


def param_combinations(grid: Mapping[str, Sequence[Any]]) -> tuple[Mapping[str, Any], ...]:
    """把参数候选值展开成笛卡尔积，顺序固定。

    参数名按字典序、取值按入参顺序：同一份网格两次展开得到同一串组合，扫描结果才能
    与上一次的逐行对齐。空网格或某个参数没有候选值直接判错——展开成零个组合会让
    「没有可跑的」显示成「跑完了，没有结果」。
    """

    if not isinstance(grid, Mapping) or not grid:
        raise ValidationError("参数网格不能为空")
    names = sorted(grid)
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(f"参数名不能为空, 实际 {name!r}")
    candidates = [list(grid[name]) for name in names]
    for name, values in zip(names, candidates, strict=True):
        if not values:
            raise ValidationError(f"参数 {name} 没有候选值")

    return tuple(
        MappingProxyType(dict(zip(names, picked, strict=True)))
        for picked in itertools.product(*candidates)
    )


def split_window(start: date, end: date) -> tuple[SplitWindow, ...]:
    """把 `[start, end]` 按 60/20/20 切成训练/验证/样本外三段。

    天数为整数除法，余下的天数归训练段（训练段是唯一允许偏大的那一段）。总天数不足
    三天时三段各留一天：切分本身不允许出现「零天的样本外段」，那等于没有样本外。
    """

    for name, value in (("start", start), ("end", end)):
        if not isinstance(value, date):
            raise ValidationError(f"切分区间的 {name} 必须是日期")
    if start > end:
        raise ValidationError(f"切分区间起点 {start} 晚于终点 {end}")

    total = (end - start).days + 1
    if total < len(SPLIT_NAMES):
        raise ValidationError(f"切分区间只有 {total} 天, 无法切成 {len(SPLIT_NAMES)} 段")

    train_days = total * _TRAIN_SHARE // _SHARE_TOTAL
    validation_days = total * _VALIDATION_SHARE // _SHARE_TOTAL
    if train_days < 1 or validation_days < 1:
        train_days, validation_days = total - len(SPLIT_NAMES) + 1, 1

    train_end = start + timedelta(days=train_days - 1)
    validation_start = train_end + DAY
    validation_end = validation_start + timedelta(days=validation_days - 1)
    test_start = validation_end + DAY
    return (
        SplitWindow(name="train", start_date=start, end_date=train_end),
        SplitWindow(name="validation", start_date=validation_start, end_date=validation_end),
        SplitWindow(name="test", start_date=test_start, end_date=end),
    )


def validate_splits(
    splits: Sequence[SplitWindow],
    *,
    start: date,
    end: date,
) -> tuple[SplitWindow, ...]:
    """校验用户给的三段切分：名字齐全、顺序固定、不重叠、无空隙、并集等于全区间。

    返回按时间先后排好的三段。并集等于全区间落到两条判据上：相邻两段必须紧挨
    （`后一段起点 = 前一段终点 + 1 天`），且首段起点就是全区间起点、末段终点就是
    全区间终点。任何一条不成立都判错，不自动修正——自动补齐会把「用户切错了」改写成
    「系统替他切了」，样本外是否真的没被用过就无从核对。
    """

    if len(splits) != len(SPLIT_NAMES):
        raise ValidationError(f"切分必须是 {list(SPLIT_NAMES)} 三段, 实际 {len(splits)} 段")
    ordered = tuple(sorted(splits, key=lambda window: window.start_date))
    names = tuple(window.name for window in ordered)
    if names != SPLIT_NAMES:
        raise ValidationError(f"切分的顺序必须是 {list(SPLIT_NAMES)}, 实际 {list(names)}")

    if ordered[0].start_date != start:
        raise ValidationError(f"首段起点 {ordered[0].start_date} 不等于全区间起点 {start}")
    if ordered[-1].end_date != end:
        raise ValidationError(f"末段终点 {ordered[-1].end_date} 不等于全区间终点 {end}")

    for previous, following in itertools.pairwise(ordered):
        expected = previous.end_date + DAY
        if following.start_date > expected:
            raise ValidationError(
                f"{previous.name} 段与 {following.name} 段之间有空隙:"
                f"{previous.end_date} 之后直到 {following.start_date} 没有归属"
            )
        if following.start_date < expected:
            raise ValidationError(
                f"{previous.name} 段与 {following.name} 段重叠:"
                f"{following.name} 段从 {following.start_date} 开始,"
                f"但 {previous.name} 段到 {previous.end_date} 才结束"
            )
    return ordered


def rank_sweep(
    rows: Sequence[SweepRow],
    *,
    metric: str,
    segment: str = TEST_SEGMENT,
    min_trades: int = 0,
) -> tuple[SweepRow, ...]:
    """按某一段的指标给扫描行排序，返回原行本身。

    这一段回测失败的行不参与排序：它没有可比较的指标，硬塞一个默认值（例如 0）会把
    「没跑出来」显示成「表现为零」。失败原因仍留在该行的 `cells` 里，界面照原样展示。
    """

    if segment not in SPLIT_NAMES:
        raise ValidationError(f"未知区段名 {segment!r}; 可选 {list(SPLIT_NAMES)}")

    rankable = tuple(
        row
        for row in rows
        if (found := row.cell(segment)) is not None and found.metrics is not None
    )
    return rank_rows(
        rankable,
        metric=metric,
        metrics_of=lambda row: row.metrics_of(segment),
        min_trades=min_trades,
    )
