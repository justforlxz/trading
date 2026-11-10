"""资金费历史采集：分页方向、结算网格、幂等落库与空值语义。

拓扑固定：真实 `OkxClient` → 线程内假 OKX → 临时 schema 的 PostgreSQL。期望值全部由
「8 小时结算网格」与假历史深度反推，不依赖上游返回顺序或本机当前时间。
"""

import ast
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import UpstreamError, ValidationError
from app.db import session_scope
from app.exchange import ExchangeError, OkxClient
from app.market import (
    FundingPoint,
    backfill_funding,
    load_funding,
    parse_funding_rows,
    upsert_funding,
)
from app.market import funding as funding_module
from tests.fakes.okx.store import FUNDING_HISTORY_DEPTH, FUNDING_INTERVAL_SECONDS

SWAP = "AAPL-USDT-SWAP"
SPOT = "XAAPL-USDT"
MOMENT = datetime(2026, 11, 10, tzinfo=UTC)
SETTLEMENT = timedelta(seconds=FUNDING_INTERVAL_SECONDS)


@pytest.fixture()
def funding_client(fake_okx_settings) -> Iterator[OkxClient]:
    """指向假 OKX 的真实客户端。"""

    client = OkxClient(settings=fake_okx_settings)
    yield client
    client.close()


def _seconds(points: list[FundingPoint]) -> list[int]:
    return [int(point.funding_time.timestamp()) for point in points]


# ------------------------------------------------------------------ 回溯采集


def test_backfill_walks_back_more_than_three_pages_to_the_earliest_record(
    funding_client,
) -> None:
    result = backfill_funding(funding_client, SWAP)

    # 360 期按每页 100 期往回翻：4 页取完，第 5 页空。
    assert result.pages == 4
    assert result.downloaded == FUNDING_HISTORY_DEPTH
    assert (result.inserted, result.updated) == (FUNDING_HISTORY_DEPTH, 0)

    points = load_funding(SWAP)
    assert len(points) == FUNDING_HISTORY_DEPTH

    stamps = _seconds(points)
    # 严格递增且无重复：相邻两页在游标处不重叠。
    assert stamps == sorted(set(stamps))
    # 结算网格恒为 8 小时，回溯不跳期。
    assert {later - earlier for earlier, later in pairwise(stamps)} == {FUNDING_INTERVAL_SECONDS}

    # 终止于该标的最早记录：再往回一页就是空的。
    assert (
        funding_module.fetch_funding_page(funding_client, SWAP, after=points[0].funding_time) == []
    )


def test_backfill_keeps_real_zero_rates_apart_from_missing(funding_client) -> None:
    backfill_funding(funding_client, SWAP)

    points = load_funding(SWAP)

    assert any(point.realized_rate == 0 for point in points)
    assert all(point.funding_rate is not None for point in points)


def test_backfilling_twice_updates_in_place(funding_client) -> None:
    backfill_funding(funding_client, SWAP)
    second = backfill_funding(funding_client, SWAP)

    assert (second.downloaded, second.inserted, second.updated) == (
        FUNDING_HISTORY_DEPTH,
        0,
        FUNDING_HISTORY_DEPTH,
    )
    assert len(load_funding(SWAP)) == FUNDING_HISTORY_DEPTH


def test_backfill_stops_when_upstream_returns_nothing(fake_okx_settings) -> None:
    """没有资金费的标的：空页只说明「没有数据」，不是故障。"""

    client = OkxClient(settings=fake_okx_settings)
    try:
        points = funding_module.fetch_funding_page(
            client, SWAP, after=datetime(1990, 1, 1, tzinfo=UTC)
        )
    finally:
        client.close()

    assert points == []


# ------------------------------------------------------------------ 纯函数


def test_parse_funding_rows_sorts_by_time_and_keeps_the_last_duplicate() -> None:
    rows = [
        {"fundingTime": "28800000", "fundingRate": "0.0002", "realizedRate": "0.0001"},
        {"fundingTime": "57600000", "fundingRate": "0.0003", "realizedRate": "0"},
        {"fundingTime": "28800000", "fundingRate": "0.0009", "realizedRate": "0.0009"},
    ]

    points = parse_funding_rows(rows, SWAP)

    assert _seconds(points) == [28800, 57600]
    assert [point.funding_rate for point in points] == [Decimal("0.0009"), Decimal("0.0003")]
    assert points[1].realized_rate == 0


def test_parse_funding_rows_treats_blank_rates_as_missing() -> None:
    rows = [
        {"fundingTime": "28800000", "fundingRate": "", "realizedRate": None},
        {"fundingTime": "57600000"},
    ]

    points = parse_funding_rows(rows, SWAP)

    assert [(point.funding_rate, point.realized_rate) for point in points] == [
        (None, None),
        (None, None),
    ]


@pytest.mark.parametrize(
    "row",
    [
        ["28800000"],  # 不是对象
        {"fundingRate": "0.0001"},  # 缺结算时刻
        {"fundingTime": "not-a-number", "fundingRate": "0.0001"},
        {"fundingTime": "28800000", "fundingRate": "abc"},
        {"fundingTime": "28800000", "realizedRate": "abc"},
    ],
)
def test_parse_funding_rows_rejects_malformed_rows(row) -> None:
    with pytest.raises(UpstreamError):
        parse_funding_rows([row], SWAP)


# ------------------------------------------------------------------ 落库语义


def test_upsert_keeps_a_real_zero_separate_from_a_missing_rate() -> None:
    real_zero = FundingPoint(
        inst_id=SWAP,
        funding_time=MOMENT,
        funding_rate=Decimal("0"),
        realized_rate=Decimal("0"),
    )
    missing = FundingPoint(
        inst_id=SWAP,
        funding_time=MOMENT + SETTLEMENT,
        funding_rate=None,
        realized_rate=None,
    )

    result = upsert_funding([real_zero, missing])

    assert (result.inserted, result.updated) == (2, 0)
    points = load_funding(SWAP)
    assert [(point.funding_rate, point.realized_rate) for point in points] == [
        (0, 0),
        (None, None),
    ]


def test_load_funding_respects_the_half_open_window() -> None:
    points = [
        FundingPoint(
            inst_id=SWAP,
            funding_time=MOMENT + index * SETTLEMENT,
            funding_rate=Decimal("0"),
            realized_rate=Decimal("0"),
        )
        for index in range(3)
    ]
    upsert_funding(points)

    windowed = load_funding(SWAP, start=MOMENT + SETTLEMENT, end=MOMENT + 2 * SETTLEMENT)

    assert [point.funding_time for point in windowed] == [MOMENT + SETTLEMENT]


def test_upsert_merges_repeated_settlement_points() -> None:
    point = FundingPoint(
        inst_id=SWAP, funding_time=MOMENT, funding_rate=Decimal("0"), realized_rate=None
    )

    result = upsert_funding([point, point])

    assert (result.inserted, result.updated) == (1, 0)
    assert len(load_funding(SWAP)) == 1


def test_upsert_of_nothing_writes_nothing() -> None:
    assert (upsert_funding([]).inserted, upsert_funding([]).updated) == (0, 0)
    assert load_funding(SWAP) == []


# ------------------------------------------------------------- 表结构与索引


def test_init_db_creates_funding_table_keyed_by_settlement() -> None:
    with session_scope() as session:
        tables = set(
            session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                )
            ).scalars()
        )
        columns = {
            row.column_name: row
            for row in session.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'funding'"
                )
            ).all()
        }
        keys = _key_columns(session, "funding")

    assert "funding" in tables
    assert set(columns) == {
        "inst_id",
        "funding_time",
        "funding_rate",
        "realized_rate",
        "updated_at",
    }
    # 两档费率都可空：缺失与「真实为 0」必须能分开表达。
    assert columns["funding_rate"].is_nullable == "YES"
    assert columns["realized_rate"].is_nullable == "YES"
    assert ("inst_id", "funding_time") in keys


def _key_columns(session: Session, table: str) -> set[tuple[str, ...]]:
    """表上的主键与唯一约束，按约束内的列顺序还原成元组集合。"""

    rows = session.execute(
        text(
            "SELECT tc.constraint_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            " AND kcu.table_schema = tc.table_schema "
            "WHERE tc.table_schema = current_schema() AND tc.table_name = :table "
            "  AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE') "
            "ORDER BY tc.constraint_name, kcu.ordinal_position"
        ),
        {"table": table},
    ).all()

    grouped: dict[str, list[str]] = {}
    for constraint_name, column_name in rows:
        grouped.setdefault(constraint_name, []).append(column_name)
    return {tuple(columns) for columns in grouped.values()}


# ------------------------------------------------------------------ 分页方向


def test_backfill_never_uses_the_before_direction() -> None:
    """上游 `before` 是往未来翻；回溯只能用 `after`，否则会无限打转。"""

    tree = ast.parse(Path(funding_module.__file__).read_text(encoding="utf-8"))

    names = {node.arg for node in ast.walk(tree) if isinstance(node, ast.keyword) and node.arg}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "before" not in names


# --------------------------------------------------------------------- 错误路径


def test_backfill_propagates_upstream_failure_and_writes_nothing(
    fake_okx_settings, fake_okx_server
) -> None:
    fake_okx_server.scenarios.activate("upstream_error")
    client = OkxClient(settings=fake_okx_settings)
    try:
        with pytest.raises(ExchangeError):
            backfill_funding(client, SWAP)
    finally:
        client.close()

    assert load_funding(SWAP) == []


def test_backfill_rejects_spot_instruments(funding_client) -> None:
    """资金费是永续合约独有的；现货按上游规则报错。"""

    with pytest.raises(ExchangeError):
        backfill_funding(funding_client, SPOT)

    assert load_funding(SPOT) == []


def test_backfill_rejects_unknown_instruments(funding_client) -> None:
    with pytest.raises(ExchangeError):
        backfill_funding(funding_client, "NOPE-USDT-SWAP")


@pytest.mark.parametrize("page_limit", [0, 101])
def test_backfill_rejects_page_limits_outside_the_upstream_cap(funding_client, page_limit) -> None:
    with pytest.raises(ValidationError):
        backfill_funding(funding_client, SWAP, page_limit=page_limit)


def test_fetch_page_rejects_naive_cursor(funding_client) -> None:
    with pytest.raises(ValidationError):
        funding_module.fetch_funding_page(funding_client, SWAP, after=datetime(2026, 11, 10))
