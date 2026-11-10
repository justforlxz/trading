"""全类别标的夹具的不变量。

`tests/fixtures/okx/instruments_all_2026-11-10.json` 是测试夹具，不是实时行情。
它保证的是数据形状：两类 `instType` 都在、四类 `instCategory` 都在（含上游未
下发的空串），因此「扫描两类全部可交易标的」的用例不必自己造数据。

另一份 `instruments_2026-11-10.json` 只含代币化股票，用途不同，两份并存。
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.factories.instruments import (
    ALL_INSTRUMENT_SNAPSHOT_PATH,
    EXPECTED_ALL_CATEGORY_COUNTS,
    EXPECTED_ALL_COUNTS,
    INST_CATEGORIES,
    load_all_instruments,
    load_all_snapshot,
    load_instruments,
    make_instrument_row,
)

# 每行必须齐全的字段：标的身份、类别、状态与精度。
REQUIRED_FIELDS = ("instId", "instType", "instCategory", "state", "tickSz", "lotSz", "minSz")
INSTRUMENTS_PATH = "/api/v5/public/instruments"
RECORDING_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "record_okx_instruments.py"
)


@pytest.fixture(scope="module")
def snapshot() -> dict[str, Any]:
    return load_all_snapshot()


@pytest.fixture(scope="module")
def rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = snapshot["instruments"]
    return rows


def test_fixture_covers_both_inst_types(rows: list[dict[str, Any]]) -> None:
    assert {row["instType"] for row in rows} == {"SPOT", "SWAP"}
    assert EXPECTED_ALL_COUNTS["SPOT"] > 0
    assert EXPECTED_ALL_COUNTS["SWAP"] > 0


def test_fixture_covers_every_inst_category(rows: list[dict[str, Any]]) -> None:
    """`3` 代币化股票、`1` 加密、`4` 代币化商品与空串都必须出现。"""

    assert set(INST_CATEGORIES) <= {row["instCategory"] for row in rows}

    for inst_type in ("SPOT", "SWAP"):
        categories = {row["instCategory"] for row in rows if row["instType"] == inst_type}
        assert {"1", "3", "4"} <= categories


def test_fixture_counts_are_frozen(snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """计数漂移说明夹具被改动过，下游依赖的规模数字随之失真。"""

    meta = snapshot["meta"]

    assert meta["counts"] == EXPECTED_ALL_COUNTS
    assert meta["category_counts"] == EXPECTED_ALL_CATEGORY_COUNTS
    assert sum(meta["counts"].values()) == len(rows)
    assert sum(meta["category_counts"].values()) == len(rows)


def test_counts_match_the_rows_they_describe(rows: list[dict[str, Any]]) -> None:
    """`meta` 里的计数必须与逐行实际统计一致，不只是自己加得起来。"""

    actual: dict[str, int] = {}
    for row in rows:
        actual[row["instType"]] = actual.get(row["instType"], 0) + 1
    actual_categories: dict[str, int] = {}
    for row in rows:
        actual_categories[row["instCategory"]] = actual_categories.get(row["instCategory"], 0) + 1

    assert actual == EXPECTED_ALL_COUNTS
    assert actual_categories == EXPECTED_ALL_CATEGORY_COUNTS


def test_every_row_carries_the_required_fields(rows: list[dict[str, Any]]) -> None:
    assert rows
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert field in row, f"{row.get('instId')} 缺字段 {field}"
            assert isinstance(row[field], str), f"{row.get('instId')} 的 {field} 不是字符串"
        # 身份与状态不允许为空；`instCategory` 上游会给空串，精度字段 preopen 行也为空。
        for field in ("instId", "instType", "state"):
            assert row[field], f"{row.get('instId')} 的 {field} 为空"


def test_fixture_is_labelled_as_test_data(snapshot: dict[str, Any]) -> None:
    meta = snapshot["meta"]

    assert meta["kind"] == "test_fixture_frozen_snapshot"
    assert "测试夹具" in meta["purpose"]
    assert "不是实时行情" in meta["purpose"]
    assert meta["source"].startswith("https://www.okx.com/")
    assert meta["captured_at"]


def test_loaded_rows_are_the_fixture_rows(rows: list[dict[str, Any]]) -> None:
    """工厂加载的就是夹具本身，不做二次筛选。"""

    assert load_all_instruments() == rows


@pytest.mark.parametrize("inst_type", ["SPOT", "SWAP"])
def test_fake_server_returns_the_fixture_rows_per_inst_type(
    fake_okx_app: FastAPI, rows: list[dict[str, Any]], inst_type: str
) -> None:
    """假 server 的条数等于夹具里该类别的行数——默认数据集已换成全类别快照。"""

    expected = [row for row in rows if row["instType"] == inst_type]
    with TestClient(fake_okx_app) as api:
        payload = api.get(INSTRUMENTS_PATH, params={"instType": inst_type}).json()

    assert payload["code"] == "0"
    assert payload["data"] == expected


@pytest.mark.parametrize("inst_category", INST_CATEGORIES)
def test_factory_builds_rows_for_every_inst_category(inst_category: str) -> None:
    row = make_instrument_row(inst_category=inst_category)

    assert row["instCategory"] == inst_category


def test_recording_script_projects_the_fixture_fields() -> None:
    """录制脚本的行字段与默认输出路径必须与夹具一致，否则重录会产生另一种形状。"""

    spec = importlib.util.spec_from_file_location("record_okx_instruments", RECORDING_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    projected = module.project_row({field: f"v-{field}" for field in module.FIELDS})

    assert tuple(projected) == module.FIELDS
    assert set(projected) == set(load_all_instruments()[0])
    assert module.default_output_path(datetime(2026, 11, 10, tzinfo=UTC)) == (
        ALL_INSTRUMENT_SNAPSHOT_PATH
    )


def test_tokenized_equity_snapshot_is_untouched() -> None:
    """原快照保留：它撑起代币化股票相关的既有测试，不被全类别快照替代。"""

    rows = load_instruments()

    assert len(rows) == 429
    assert {row["instType"] for row in rows} == {"SPOT", "SWAP"}
    assert {row["instCategory"] for row in rows} == {"3"}
