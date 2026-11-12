"""参数扫描作业：3 标的 × 2 参数组合 = 6 条结果，并发峰值由队列自身上报。

栅栏（`threading.Barrier(2)`）保证「同时进入回测的格子」必须两两会合：若队列实际串行，
栅栏超时抛错，那一格变成失败、峰值也到不了 2，用例同样会红。因此这里的并发断言不是
从耗时或日志猜出来的。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

import pytest

from app.backtest import SweepRow, rank_sweep, split_window
from app.core import ValidationError
from app.jobs import (
    DEFAULT_MAX_CONCURRENCY,
    SweepOutcome,
    SweepPlan,
    plan_sweep,
    run_sweep,
)

BARRIER_TIMEOUT = 10
START = date(2026, 1, 1)
END = date(2026, 3, 31)

SYMBOLS = ("XAAPL-USDT", "XMSFT-USDT", "XTSLA-USDT")
GRID = {"fast": [7, 14]}


def metrics_for(inst_id: str, fast: int, segment: str) -> Mapping[str, Decimal]:
    """按（标的, 参数, 区段）造一份可比的指标：收益随 fast 递减、随区段变化。"""

    base = Decimal("0.30") - Decimal(str(fast)) / Decimal("100")
    bump = {"train": "0.00", "validation": "0.01", "test": "0.02"}[segment]
    return {
        "total_return": base + Decimal(bump),
        "max_drawdown": Decimal("0.10"),
        "sharpe": Decimal("1.0"),
        "profit_factor": Decimal("1.5"),
        "trade_count": Decimal("30"),
    }


def plan() -> SweepPlan:
    return plan_sweep(
        inst_ids=SYMBOLS,
        param_grid=GRID,
        start_date=START,
        end_date=END,
    )


def test_sweep_expands_three_symbols_and_two_combinations_into_six_rows() -> None:
    barrier = threading.Barrier(DEFAULT_MAX_CONCURRENCY, timeout=BARRIER_TIMEOUT)
    calls: list[tuple[str, dict[str, object], str]] = []
    guard = threading.Lock()

    def runner(inst_id: str, params: Mapping[str, object], segment) -> Mapping[str, Decimal]:
        barrier.wait()
        with guard:
            calls.append((inst_id, dict(params), segment.name))
        return metrics_for(inst_id, int(params["fast"]), segment.name)  # type: ignore[arg-type]

    outcome: SweepOutcome = run_sweep(plan(), runner)  # type: ignore[arg-type]

    assert len(outcome.rows) == 6
    assert {(row.inst_id, row.params["fast"]) for row in outcome.rows} == {
        (inst_id, fast) for inst_id in SYMBOLS for fast in GRID["fast"]
    }
    # 行按「标的 → 参数组合」排序，因此每个标的占连续两行。
    assert [row.params["fast"] for row in outcome.rows] == [7, 14] * 3
    assert [row.inst_id for row in outcome.rows] == [SYMBOLS[0]] * 2 + [SYMBOLS[1]] * 2 + [
        SYMBOLS[2]
    ] * 2

    # 每行三段、按计划里的区段顺序装回。
    assert [tuple(cell.segment.name for cell in row.cells) for row in outcome.rows] == [
        ("train", "validation", "test")
    ] * 6
    assert all(cell.metrics is not None for row in outcome.rows for cell in row.cells)

    # 6 行 × 3 段 = 18 次独立回测，一次不多一次不少。
    assert len(calls) == 6 * 3
    assert {(inst_id, params["fast"], segment) for inst_id, params, segment in calls} == {
        (inst_id, fast, segment)
        for inst_id in SYMBOLS
        for fast in GRID["fast"]
        for segment in ("train", "validation", "test")
    }

    # 峰值由队列自身上报：上限 2，实际到达 2。
    assert outcome.max_concurrency == 2
    assert outcome.peak_running <= 2
    assert outcome.peak_running == 2


def test_sweep_respects_an_explicit_concurrency_of_one() -> None:
    def runner(inst_id: str, params: Mapping[str, object], segment) -> Mapping[str, Decimal]:
        return metrics_for(inst_id, int(params["fast"]), segment.name)  # type: ignore[arg-type]

    outcome = run_sweep(plan(), runner, max_concurrency=1)  # type: ignore[arg-type]

    assert outcome.peak_running == 1
    assert len(outcome.rows) == 6


def test_sweep_keeps_a_failed_cell_from_killing_the_batch() -> None:
    def runner(inst_id: str, params: Mapping[str, object], segment) -> Mapping[str, Decimal]:
        if inst_id == SYMBOLS[1] and segment.name == "test":
            raise RuntimeError("该标的没有日线")
        return metrics_for(inst_id, int(params["fast"]), segment.name)  # type: ignore[arg-type]

    outcome = run_sweep(plan(), runner)  # type: ignore[arg-type]

    failed = [cell for row in outcome.rows for cell in row.cells if cell.error is not None]
    assert len(failed) == 2, "XMSFT 的两个参数组合都在样本外段失败"
    assert all("RuntimeError: 该标的没有日线" in (cell.error or "") for cell in failed)
    assert len([cell for row in outcome.rows for cell in row.cells if cell.metrics]) == 16


def test_sweep_regroups_rows_by_symbol_and_combination() -> None:
    """同一格在并发完成顺序变化时也必须落回自己那一行。"""

    def runner(inst_id: str, params: Mapping[str, object], segment) -> Mapping[str, Decimal]:
        return metrics_for(inst_id, int(params["fast"]), segment.name)  # type: ignore[arg-type]

    outcome = run_sweep(plan(), runner, max_concurrency=4)  # type: ignore[arg-type]

    for row in outcome.rows:
        train = row.cell("train")
        assert train is not None and train.metrics is not None
        expected = metrics_for(row.inst_id, int(row.params["fast"]), "train")
        assert train.metrics["total_return"] == expected["total_return"]


def test_sweep_rows_rank_by_the_out_of_sample_segment() -> None:
    def runner(inst_id: str, params: Mapping[str, object], segment) -> Mapping[str, Decimal]:
        return metrics_for(inst_id, int(params["fast"]), segment.name)  # type: ignore[arg-type]

    outcome = run_sweep(plan(), runner)  # type: ignore[arg-type]
    ranked: tuple[SweepRow, ...] = rank_sweep(outcome.rows, metric="total_return")

    assert len(ranked) == 6
    # fast=7 的样本外收益更高，因此六个 fast=7 的行排在前三（每标的各一行）。
    assert {row.params["fast"] for row in ranked[:3]} == {7}
    assert all(row.cell("test") is not None for row in ranked)


def test_plan_sweep_defaults_to_three_contiguous_segments() -> None:
    built = plan()

    assert built.splits == split_window(START, END)
    assert built.splits[0].start_date == START
    assert built.splits[-1].end_date == END
    assert len(built.tasks()) == 3 * 2 * 3


def test_plan_sweep_rejects_overlapping_splits() -> None:
    train, validation, test = split_window(START, END)
    overlapping = (
        train,
        type(validation)(
            name="validation",
            start_date=train.end_date,
            end_date=validation.end_date,
        ),
        test,
    )

    with pytest.raises(ValidationError, match="重叠"):
        plan_sweep(
            inst_ids=SYMBOLS,
            param_grid=GRID,
            start_date=START,
            end_date=END,
            splits=overlapping,
        )


def test_plan_sweep_rejects_an_empty_symbol_set() -> None:
    with pytest.raises(ValidationError, match="扫描计划没有标的"):
        plan_sweep(
            inst_ids=(),
            param_grid=GRID,
            start_date=START,
            end_date=END,
        )


def test_plan_sweep_rejects_an_empty_param_grid() -> None:
    with pytest.raises(ValidationError, match="参数网格不能为空"):
        plan_sweep(
            inst_ids=SYMBOLS,
            param_grid={},
            start_date=START,
            end_date=END,
        )


def test_plan_sweep_rejects_a_plan_without_segments() -> None:
    with pytest.raises(ValidationError, match="扫描计划没有区段"):
        SweepPlan(
            inst_ids=SYMBOLS,
            combinations=({"fast": 7},),
            splits=(),
        )


def test_run_sweep_rejects_a_plan_of_the_wrong_type() -> None:
    with pytest.raises(ValidationError, match="扫描计划必须是 SweepPlan"):
        run_sweep("plan", lambda *arguments: {})  # type: ignore[arg-type]


def test_run_sweep_rejects_a_runner_that_is_not_callable() -> None:
    with pytest.raises(ValidationError, match="执行入口必须可调用"):
        run_sweep(plan(), "runner")  # type: ignore[arg-type]
