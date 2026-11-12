"""参数扫描作业：标的集合 × 参数笛卡尔积 × 三段切分，走进程内队列并发跑。

## 一次调用只做一件事

`run_sweep` 把「要跑哪些格子」展开成任务、交给队列按并发上限跑、再把结果装回扫描行。
它不读库、不读行情、不认识策略：每一格实际怎么跑由调用方注入的 `runner` 决定。这样本
作业只对「调度与拼装」负责，回测本身的输入（行情、目标组合、成本）由装配层自己备齐。

## 每格都必须是一次独立回测

`runner` 的契约写死一件事：**每调用一次就是一次独立回测**。T4.5 的 `FundingSettlement`
持有跨结算点的状态，T4.7 之后由 `run_backtest` 在每次开始时调用 `begin_run()` 重置账本，
串行复用同一实例已经安全；但同一实例仍不得同时被多个并发格子共用，否则两次回测的
重置会互相穿插。runner 缓存实例时必须保证同一时刻只有一个格子在用。

## 失败留在格子里

一格回测失败（缺 K 线、标的没有该周期的数据、参数不成立）不会中断整批：错误进
`SweepCell.error`，同批其余格子照常跑完。排到哪一段失败的行不参与该段的排序
（见 `sweep.rank_sweep`）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.backtest import (
    SplitWindow,
    SweepCell,
    SweepRow,
    param_combinations,
    split_window,
    validate_splits,
)
from app.core import ValidationError
from app.jobs.queue import DEFAULT_MAX_CONCURRENCY, run_tasks

__all__ = ["SweepOutcome", "SweepPlan", "plan_sweep", "run_sweep"]

#: 一格的执行入口：标的标识 + 参数组合 + 回测区间 → 指标映射。
#:
#: 指标映射的键与 `metrics.compute_metrics` 一致（`total_return` / `max_drawdown` /
#: `sharpe` / `profit_factor` / `trade_count` 等）。每次调用必须是独立回测，不得复用
#: 结算实例。
SweepRunner = Callable[[str, Mapping[str, Any], SplitWindow], Mapping[str, Decimal]]


@dataclass(frozen=True, slots=True)
class SweepPlan:
    """展开好的扫描计划：标的 × 参数组合 × 三段区间，三者都是固定序列。"""

    inst_ids: tuple[str, ...]
    combinations: tuple[Mapping[str, Any], ...]
    splits: tuple[SplitWindow, ...]

    def __post_init__(self) -> None:
        if not self.inst_ids:
            raise ValidationError("扫描计划没有标的")
        for inst_id in self.inst_ids:
            if not isinstance(inst_id, str) or not inst_id.strip():
                raise ValidationError(f"扫描计划里有空标的: {inst_id!r}")
        if not self.combinations:
            raise ValidationError("扫描计划没有参数组合")
        for combination in self.combinations:
            if not isinstance(combination, Mapping):
                raise ValidationError("扫描计划的参数组合必须是映射")
        if not self.splits:
            raise ValidationError("扫描计划没有区段")

    def tasks(self) -> tuple[tuple[str, Mapping[str, Any], SplitWindow], ...]:
        """按「标的 → 参数组合 → 区段」的顺序展开成待跑的格子清单。

        这个顺序就是结果行的顺序：并发完成先后不同的任务，最终仍按同一串顺序拼回去，
        因此同一份库、同一份计划跑两次得到同一排结果。
        """

        return tuple(
            (inst_id, combination, segment)
            for inst_id in self.inst_ids
            for combination in self.combinations
            for segment in self.splits
        )


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    """一次扫描的结果：逐行结果 + 队列自身上报的并发峰值。"""

    rows: tuple[SweepRow, ...]
    peak_running: int
    max_concurrency: int


def plan_sweep(
    *,
    inst_ids: Sequence[str],
    param_grid: Mapping[str, Sequence[Any]],
    start_date: date,
    end_date: date,
    splits: Sequence[SplitWindow] = (),
) -> SweepPlan:
    """把标的、参数网格与区间整理成扫描计划。

    不给切分时按 60/20/20 自动切三段；给了就逐条校验（名称齐全、不重叠、无空隙、
    并集等于 `[start_date, end_date]`）。校验失败直接判错，不自动修正用户给的切分——
    自动补齐会让「样本外」到底有没有混进训练段无从核对。
    """

    candidates = tuple(split_window(start_date, end_date)) if not splits else tuple(splits)
    ordered = validate_splits(candidates, start=start_date, end=end_date)
    return SweepPlan(
        inst_ids=tuple(inst_ids),
        combinations=param_combinations(param_grid),
        splits=ordered,
    )


def run_sweep(
    plan: SweepPlan,
    runner: SweepRunner,
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> SweepOutcome:
    """按计划跑完整次扫描，返回逐行结果与并发峰值。

    一行的三格（训练/验证/样本外）跑完后按计划里的区段顺序装回同一行；这一行里任何
    一格失败都只影响它自己，其余格子照常回来。
    """

    if not isinstance(plan, SweepPlan):
        raise ValidationError("扫描计划必须是 SweepPlan")
    if not callable(runner):
        raise ValidationError("扫描的执行入口必须可调用")

    cells = plan.tasks()
    report = run_tasks(
        [
            lambda inst_id=inst_id, params=params, segment=segment: runner(inst_id, params, segment)
            for inst_id, params, segment in cells
        ],
        max_concurrency=max_concurrency,
    )

    rows: list[SweepRow] = []
    outcome_index = 0
    for inst_id in plan.inst_ids:
        for combination in plan.combinations:
            built: list[SweepCell] = []
            for segment in plan.splits:
                outcome = report.outcomes[outcome_index]
                outcome_index += 1
                built.append(
                    SweepCell(
                        segment=segment,
                        metrics=outcome.value,
                        error=outcome.error,
                    )
                )
            rows.append(SweepRow(inst_id=inst_id, params=combination, cells=tuple(built)))

    return SweepOutcome(
        rows=tuple(rows),
        peak_running=report.peak_running,
        max_concurrency=report.max_concurrency,
    )
