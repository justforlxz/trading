"""参数扫描与批量排序：笛卡尔积、三段切分、四个指标的排序、交易次数过滤。

期望值都由「手工摆出来的指标」反推：每一行的四个指标与交易次数是写死的，排序后的
顺序、被过滤掉的行、被排除的失败格都能逐条对上，不依赖任何行情或回测计算结果。

另有一条「防过拟合」的行为断言：排序默认按**样本外**段，且不给任何一行加「最优」
标记——`app/backtest` 与 `app/jobs` 的源码里不存在 `best` / `optimal` / `winner` 这类
标识符。
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import fields
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.backtest import (
    SplitWindow,
    SweepCell,
    SweepRow,
    param_combinations,
    rank_rows,
    rank_sweep,
    split_window,
    validate_splits,
)
from app.core import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]

START = date(2026, 1, 1)
END = date(2026, 4, 10)  # 含首尾共 100 天：训练 60 天、验证 20 天、样本外 20 天。


def metrics(
    *,
    total_return: str = "0.10",
    max_drawdown: str = "0.05",
    sharpe: str = "1.2",
    profit_factor: str = "1.5",
    trade_count: str = "10",
) -> Mapping[str, Decimal]:
    """手写一份指标映射；五个键都对得上排序与过滤用到的名字。"""

    return {
        "total_return": Decimal(total_return),
        "max_drawdown": Decimal(max_drawdown),
        "sharpe": Decimal(sharpe),
        "profit_factor": Decimal(profit_factor),
        "trade_count": Decimal(trade_count),
    }


@pytest.fixture(scope="module")
def splits() -> tuple[SplitWindow, ...]:
    return split_window(START, END)


def sweep_row(
    inst_id: str,
    fast: int,
    *,
    train: Mapping[str, Decimal] | None = None,
    validation: Mapping[str, Decimal] | None = None,
    test: Mapping[str, Decimal] | None = None,
    failing: str | None = None,
) -> SweepRow:
    """造一行扫描结果；给 `failing` 时把该段做成失败格。"""

    cells = []
    for segment, values in zip(
        split_window(START, END),
        (train or metrics(), validation or metrics(), test or metrics()),
        strict=True,
    ):
        if failing == segment.name:
            cells.append(SweepCell(segment=segment, error="KeyError: 缺 K 线"))
        else:
            cells.append(SweepCell(segment=segment, metrics=values))
    return SweepRow(inst_id=inst_id, params={"fast": fast}, cells=tuple(cells))


# ------------------------------------------------------------------ 参数笛卡尔积


def test_param_combinations_expands_the_cartesian_product_in_fixed_order() -> None:
    combos = param_combinations({"slow": [20, 30], "fast": [7, 14]})

    assert combos == (
        {"fast": 7, "slow": 20},
        {"fast": 7, "slow": 30},
        {"fast": 14, "slow": 20},
        {"fast": 14, "slow": 30},
    )
    # 参数名按字典序，入参的键顺序不影响结果。
    assert combos == param_combinations({"fast": [7, 14], "slow": [20, 30]})


def test_param_combinations_single_parameter_keeps_candidate_order() -> None:
    assert param_combinations({"period": [21, 7, 14]}) == (
        {"period": 21},
        {"period": 7},
        {"period": 14},
    )


def test_param_combinations_are_read_only() -> None:
    (combo,) = param_combinations({"period": [7]})

    with pytest.raises(TypeError):
        combo["period"] = 14  # type: ignore[index]


def test_param_combinations_rejects_an_empty_grid() -> None:
    with pytest.raises(ValidationError, match="参数网格不能为空"):
        param_combinations({})


def test_param_combinations_rejects_a_parameter_without_candidates() -> None:
    with pytest.raises(ValidationError, match="参数 fast 没有候选值"):
        param_combinations({"fast": []})


# ---------------------------------------------------------------- 三段区间切分


def test_split_window_covers_the_whole_range_without_overlap(
    splits: tuple[SplitWindow, ...],
) -> None:
    assert tuple(window.name for window in splits) == ("train", "validation", "test")
    assert splits[0].start_date == START
    assert splits[-1].end_date == END

    covered: set[date] = set()
    for window in splits:
        days = {
            window.start_date + timedelta(days=offset)
            for offset in range((window.end_date - window.start_date).days + 1)
        }
        assert not covered & days, f"{window.name} 段与前面的段落重叠"
        covered |= days

    whole = {START + timedelta(days=offset) for offset in range((END - START).days + 1)}
    assert covered == whole, "三段并集必须等于全区间"


def test_split_window_defaults_to_sixty_twenty_twenty(splits: tuple[SplitWindow, ...]) -> None:
    assert tuple((window.end_date - window.start_date).days + 1 for window in splits) == (
        60,
        20,
        20,
    )


def test_split_window_keeps_one_day_per_segment_on_a_three_day_range() -> None:
    tiny = split_window(date(2026, 5, 1), date(2026, 5, 3))

    assert [(window.start_date, window.end_date) for window in tiny] == [
        (date(2026, 5, 1), date(2026, 5, 1)),
        (date(2026, 5, 2), date(2026, 5, 2)),
        (date(2026, 5, 3), date(2026, 5, 3)),
    ]


def test_split_window_rejects_a_range_shorter_than_three_days() -> None:
    with pytest.raises(ValidationError, match="无法切成 3 段"):
        split_window(date(2026, 5, 1), date(2026, 5, 2))


def test_split_window_rejects_a_reversed_range() -> None:
    with pytest.raises(ValidationError, match="晚于终点"):
        split_window(END, START)


def test_validate_splits_accepts_the_default_split(splits: tuple[SplitWindow, ...]) -> None:
    assert validate_splits(splits, start=START, end=END) == splits


def test_validate_splits_rejects_overlapping_segments(
    splits: tuple[SplitWindow, ...],
) -> None:
    train, validation, test = splits
    overlapping = (
        train,
        SplitWindow(
            name="validation",
            start_date=train.end_date,
            end_date=validation.end_date,
        ),
        test,
    )

    with pytest.raises(ValidationError, match="重叠"):
        validate_splits(overlapping, start=START, end=END)


def test_validate_splits_rejects_a_gap_between_segments(
    splits: tuple[SplitWindow, ...],
) -> None:
    train, validation, test = splits
    gapped = (
        SplitWindow(name="train", start_date=train.start_date, end_date=train.end_date),
        SplitWindow(
            name="validation",
            start_date=validation.start_date + timedelta(days=1),
            end_date=validation.end_date + timedelta(days=1),
        ),
        test,
    )

    with pytest.raises(ValidationError, match="空隙"):
        validate_splits(gapped, start=START, end=END)


def test_validate_splits_rejects_the_wrong_names(splits: tuple[SplitWindow, ...]) -> None:
    train, validation, test = splits
    renamed = (
        SplitWindow(name="validation", start_date=train.start_date, end_date=train.end_date),
        SplitWindow(name="train", start_date=validation.start_date, end_date=validation.end_date),
        test,
    )

    with pytest.raises(ValidationError, match="顺序必须是"):
        validate_splits(renamed, start=START, end=END)


def test_validate_splits_rejects_a_missing_segment(splits: tuple[SplitWindow, ...]) -> None:
    with pytest.raises(ValidationError, match="必须是 \\['train', 'validation', 'test'\\] 三段"):
        validate_splits(splits[:2], start=START, end=END)


def test_validate_splits_rejects_a_range_that_does_not_match(
    splits: tuple[SplitWindow, ...],
) -> None:
    with pytest.raises(ValidationError, match="不等于全区间起点"):
        validate_splits(splits, start=START - timedelta(days=1), end=END)

    with pytest.raises(ValidationError, match="不等于全区间终点"):
        validate_splits(splits, start=START, end=END + timedelta(days=1))


def test_split_window_rejects_an_unknown_segment_name() -> None:
    with pytest.raises(ValidationError, match="未知区段名"):
        SplitWindow(name="holdout", start_date=START, end_date=END)


# -------------------------------------------------------------------- 扫描行


def test_sweep_row_reports_the_metrics_of_one_segment(splits: tuple[SplitWindow, ...]) -> None:
    row = sweep_row("XAAPL-USDT", 7, test=metrics(total_return="0.42"))

    assert row.metrics_of("test")["total_return"] == Decimal("0.42")
    assert row.cell("validation") is not None


def test_sweep_row_reports_a_failed_segment_with_its_cause() -> None:
    row = sweep_row("XAAPL-USDT", 7, failing="test")

    with pytest.raises(ValidationError, match="test 段回测失败: KeyError: 缺 K 线"):
        row.metrics_of("test")


def test_sweep_row_reports_a_missing_segment() -> None:
    train, validation, _ = split_window(START, END)
    row = SweepRow(
        inst_id="XAAPL-USDT",
        params={"fast": 7},
        cells=(
            SweepCell(segment=train, metrics=metrics()),
            SweepCell(segment=validation, metrics=metrics()),
        ),
    )

    assert row.cell("test") is None
    with pytest.raises(ValidationError, match="没有 test 段的回测结果"):
        row.metrics_of("test")


def test_sweep_cell_requires_exactly_one_of_metrics_and_error(
    splits: tuple[SplitWindow, ...],
) -> None:
    train = splits[0]

    with pytest.raises(ValidationError, match="必须带指标或错误之一"):
        SweepCell(segment=train)
    with pytest.raises(ValidationError, match="不能同时带指标和错误"):
        SweepCell(segment=train, metrics=metrics(), error="boom")


def test_sweep_row_rejects_a_blank_symbol(splits: tuple[SplitWindow, ...]) -> None:
    with pytest.raises(ValidationError, match="扫描行的标的不能为空"):
        SweepRow(
            inst_id=" ",
            params={"fast": 7},
            cells=(SweepCell(segment=splits[0], metrics=metrics()),),
        )


def test_sweep_row_rejects_duplicate_segments(splits: tuple[SplitWindow, ...]) -> None:
    with pytest.raises(ValidationError, match="重复区段"):
        SweepRow(
            inst_id="XAAPL-USDT",
            params={"fast": 7},
            cells=(
                SweepCell(segment=splits[0], metrics=metrics()),
                SweepCell(segment=splits[0], metrics=metrics()),
            ),
        )


# ------------------------------------------------------------------ 排序与过滤


@pytest.mark.parametrize(
    ("metric", "ordered_returns"),
    [
        ("total_return", ("0.30", "0.20", "0.10")),
        ("sharpe", ("2.0", "1.0", "0.5")),
        ("profit_factor", ("3.0", "2.0", "1.1")),
    ],
)
def test_rank_rows_sorts_descending_for_growth_metrics(
    metric: str, ordered_returns: tuple[str, str, str]
) -> None:
    rows = [
        {"id": "c", metric: Decimal(ordered_returns[2])},
        {"id": "a", metric: Decimal(ordered_returns[0])},
        {"id": "b", metric: Decimal(ordered_returns[1])},
    ]

    ranked = rank_rows(rows, metric=metric, metrics_of=lambda row: row)

    assert [row["id"] for row in ranked] == ["a", "b", "c"]


def test_rank_rows_sorts_max_drawdown_ascending() -> None:
    """回撤是正数幅度：越小越好，因此升序，别把回撤最大的排到第一。"""

    rows = [
        {"id": "deep", "max_drawdown": Decimal("0.30")},
        {"id": "shallow", "max_drawdown": Decimal("0.05")},
        {"id": "middle", "max_drawdown": Decimal("0.12")},
    ]

    ranked = rank_rows(rows, metric="max_drawdown", metrics_of=lambda row: row)

    assert [row["id"] for row in ranked] == ["shallow", "middle", "deep"]


def test_rank_rows_returns_the_same_objects_in_a_new_order() -> None:
    first = {"id": "a", "total_return": Decimal("0.1"), "trade_count": Decimal("3")}
    second = {"id": "b", "total_return": Decimal("0.2"), "trade_count": Decimal("3")}

    ranked = rank_rows([first, second], metric="total_return", metrics_of=lambda row: row)

    assert ranked == (second, first)
    assert ranked[0] is second
    assert ranked[1] is first


def test_rank_rows_keeps_input_order_for_ties() -> None:
    rows = [
        {"id": "first", "total_return": Decimal("0.1"), "trade_count": Decimal("3")},
        {"id": "second", "total_return": Decimal("0.1"), "trade_count": Decimal("3")},
    ]

    ranked = rank_rows(rows, metric="total_return", metrics_of=lambda row: row)

    assert [row["id"] for row in ranked] == ["first", "second"]


def test_rank_rows_filters_rows_below_the_trade_floor() -> None:
    rows = [
        {"id": "two-trades", "total_return": Decimal("0.9"), "trade_count": Decimal("2")},
        {"id": "ten-trades", "total_return": Decimal("0.1"), "trade_count": Decimal("10")},
    ]

    ranked = rank_rows(rows, metric="total_return", metrics_of=lambda row: row, min_trades=5)

    assert [row["id"] for row in ranked] == ["ten-trades"]


def test_rank_rows_accepts_an_empty_batch() -> None:
    assert rank_rows([], metric="sharpe", metrics_of=lambda row: row) == ()


def test_rank_rows_rejects_an_unknown_metric() -> None:
    with pytest.raises(ValidationError, match="未知排序指标"):
        rank_rows([], metric="calmar", metrics_of=lambda row: row)


def test_rank_rows_rejects_a_missing_metric() -> None:
    with pytest.raises(ValidationError, match="缺少指标 sharpe"):
        rank_rows(
            [{"trade_count": Decimal("3")}],
            metric="sharpe",
            metrics_of=lambda row: row,
        )


def test_rank_rows_rejects_a_missing_trade_count_when_filtering() -> None:
    with pytest.raises(ValidationError, match="缺少指标 trade_count"):
        rank_rows(
            [{"sharpe": Decimal("1")}],
            metric="sharpe",
            metrics_of=lambda row: row,
            min_trades=1,
        )


def test_rank_rows_rejects_a_non_decimal_metric() -> None:
    with pytest.raises(ValidationError, match="必须是 Decimal"):
        rank_rows(
            [{"sharpe": 1.0}],  # type: ignore[list-item]
            metric="sharpe",
            metrics_of=lambda row: row,
        )


def test_rank_rows_rejects_a_non_finite_metric() -> None:
    with pytest.raises(ValidationError, match="不是有限数"):
        rank_rows(
            [{"sharpe": Decimal("NaN")}],
            metric="sharpe",
            metrics_of=lambda row: row,
        )


def test_rank_rows_rejects_metrics_that_are_not_a_mapping() -> None:
    with pytest.raises(ValidationError, match="指标不是映射"):
        rank_rows([object()], metric="sharpe", metrics_of=lambda row: row)  # type: ignore[arg-type]


@pytest.mark.parametrize("floor", [-1, 1.5, True])
def test_rank_rows_rejects_a_bad_trade_floor(floor: object) -> None:
    with pytest.raises(ValidationError, match="交易次数下限"):
        rank_rows([], metric="sharpe", metrics_of=lambda row: row, min_trades=floor)  # type: ignore[arg-type]


def test_rank_sweep_orders_rows_by_each_ranking_metric() -> None:
    rows = (
        sweep_row("XAAPL-USDT", 7, test=metrics(total_return="0.10", sharpe="0.9")),
        sweep_row("XMSFT-USDT", 7, test=metrics(total_return="0.30", sharpe="1.8")),
        sweep_row("XTSLA-USDT", 7, test=metrics(total_return="0.20", sharpe="1.3")),
    )

    assert [row.inst_id for row in rank_sweep(rows, metric="total_return")] == [
        "XMSFT-USDT",
        "XTSLA-USDT",
        "XAAPL-USDT",
    ]
    assert [row.inst_id for row in rank_sweep(rows, metric="sharpe")] == [
        "XMSFT-USDT",
        "XTSLA-USDT",
        "XAAPL-USDT",
    ]


def test_rank_sweep_defaults_to_the_out_of_sample_segment() -> None:
    """训练段打平时，名次由样本外段决定——否则等于按「调参用的那段」挑。"""

    rows = (
        sweep_row(
            "overfit",
            7,
            train=metrics(total_return="0.50"),
            test=metrics(total_return="0.01"),
        ),
        sweep_row(
            "holds-up",
            14,
            train=metrics(total_return="0.50"),
            test=metrics(total_return="0.30"),
        ),
    )

    ranked = rank_sweep(rows, metric="total_return")

    assert [row.inst_id for row in ranked] == ["holds-up", "overfit"]
    assert all(row.cell("test") is not None for row in ranked)


def test_rank_sweep_can_rank_a_named_segment() -> None:
    rows = (
        sweep_row("overfit", 7, train=metrics(total_return="0.50")),
        sweep_row("holds-up", 14, train=metrics(total_return="0.10")),
    )

    ranked = rank_sweep(rows, metric="total_return", segment="train")

    assert [row.inst_id for row in ranked] == ["overfit", "holds-up"]


def test_rank_sweep_filters_by_the_ranked_segments_trade_count() -> None:
    rows = (
        sweep_row("thin", 7, test=metrics(total_return="0.90", trade_count="2")),
        sweep_row("thick", 14, test=metrics(total_return="0.10", trade_count="40")),
    )

    ranked = rank_sweep(rows, metric="total_return", min_trades=10)

    assert [row.inst_id for row in ranked] == ["thick"]


def test_rank_sweep_drops_rows_whose_ranked_segment_failed() -> None:
    rows = (
        sweep_row("broken", 7, failing="test"),
        sweep_row("fine", 14, test=metrics(total_return="0.01")),
    )

    ranked = rank_sweep(rows, metric="total_return")

    assert [row.inst_id for row in ranked] == ["fine"]
    broken = rows[0].cell("test")
    assert broken is not None and broken.error is not None


def test_rank_sweep_rejects_an_unknown_segment() -> None:
    with pytest.raises(ValidationError, match="未知区段名"):
        rank_sweep([], metric="sharpe", segment="holdout")


# ------------------------------------------------------- 防过拟合：不标「最优」


def test_no_identifier_elects_a_best_parameter_set() -> None:
    """源码里不存在「最优 / 推荐 / 冠军」这类标识符，只有排序。"""

    banned = {"best", "is_best", "optimal", "winner", "champion", "recommended", "pick"}
    offenders: list[str] = []

    for name in (
        "backtest/batch.py",
        "backtest/sweep.py",
        "jobs/sweep.py",
        "jobs/scope.py",
        "jobs/queue.py",
    ):
        path = BACKEND_ROOT / "app" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            found: str | None = None
            if isinstance(node, (ast.Name, ast.arg, ast.Attribute)):
                found = getattr(node, "id", None) or getattr(node, "attr", None) or node.arg
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                found = node.name
            if found is not None and found.lower() in banned:
                offenders.append(f"{name}:{node.lineno} {found}")

    assert not offenders, "扫描结果只能并列展示, 不得标出最优项:" + "; ".join(offenders)


def test_ranking_never_marks_a_row_as_the_best() -> None:
    """排完序行还是那些行：没有多出来的标记字段，也没有被摘出去的那一行。"""

    rows = (
        sweep_row("XAAPL-USDT", 7, test=metrics(total_return="0.10")),
        sweep_row("XMSFT-USDT", 7, test=metrics(total_return="0.30")),
    )

    ranked = rank_sweep(rows, metric="total_return")

    assert len(ranked) == len(rows)
    assert {id(row) for row in ranked} == {id(row) for row in rows}
    field_names = {field.name for field in fields(SweepRow)}
    assert field_names == {"inst_id", "params", "cells"}
    cell_fields = {field.name for field in fields(SweepCell)}
    assert cell_fields == {"segment", "metrics", "error"}
