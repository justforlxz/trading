"""整批容错：用真实抓取的现货快照验证空币种行不连坐整批标的。

夹具是 2026-11-10 从 OKX 公共接口抓下来的一整份 `?instType=SPOT` 应答（1221 行），
不是手造的行：被这个缺口掩盖掉的正是「上游真实应答里存在还没下发币种的 preopen 行」
这一事实。夹具里那 5 行的 `baseCcy` / `quoteCcy` 是空串，一旦按行校验出错就整批回滚，
1216 条 `live` 标的会一条都进不了库。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db import init_db, session_scope
from app.exchange.okx.instruments import parse_instruments
from app.instrument import Instrument, SyncReport, sync_instruments

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "okx"
FIXTURE_PATH = FIXTURES_DIR / "instruments_spot_live_2026-11-10.json"


@pytest.fixture(autouse=True)
def _schema() -> None:
    """每个用例都在临时 schema 里执行迁移。"""

    init_db()


def _document() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


def _rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _document()["instruments"]
    return rows


def _meta() -> dict[str, Any]:
    meta: dict[str, Any] = _document()["meta"]
    return meta


def _has_currency(row: dict[str, Any]) -> bool:
    return bool(row["baseCcy"].strip() and row["quoteCcy"].strip())


def _stored() -> tuple[int, Counter[str], list[str]]:
    """库里当前的行数、`product_key` 分布与全部 `symbol`。"""

    with session_scope() as session:
        rows = list(session.scalars(select(Instrument)))
    return len(rows), Counter(row.product_key for row in rows), [row.symbol for row in rows]


def _skip_ids(report: SyncReport) -> list[str]:
    return [skip.inst_id for skip in report.skipped]


def test_snapshot_meta_records_the_real_capture() -> None:
    rows, meta = _rows(), _meta()

    assert meta["source"].endswith("/api/v5/public/instruments?instType=SPOT")
    assert meta["captured_at"].endswith("Z")
    assert meta["counts"] == {"SPOT": len(rows)}
    assert sum(meta["state_counts"].values()) == len(rows)
    assert {row["instType"] for row in rows} == {"SPOT"}


def test_snapshot_keeps_the_upstream_gap_that_motivated_this_case() -> None:
    """夹具里必须留着上游的真实缺口，否则这条用例就退化成手造数据。"""

    incomplete = sorted(row["instId"] for row in _rows() if not _has_currency(row))

    assert incomplete
    assert incomplete == _meta()["empty_currency_inst_ids"]


def test_real_snapshot_syncs_every_complete_live_row() -> None:
    rows = _rows()
    state_counts = _meta()["state_counts"]
    complete_live = [row for row in rows if row["state"] == "live" and _has_currency(row)]

    report = sync_instruments(parse_instruments(rows))

    # 这份真实快照里每一条 live 行都带币种，因此 live 行数就是应入库行数。
    assert len(complete_live) == state_counts["live"]
    assert report.inserted == state_counts["live"]
    assert report.total == len(rows)
    assert sorted(_skip_ids(report)) == _meta()["empty_currency_inst_ids"]
    assert all(skip.reason for skip in report.skipped)

    stored, keys, symbols = _stored()
    assert stored == state_counts["live"]
    assert not set(symbols) & set(_meta()["empty_currency_inst_ids"])
    # 入库的行都有配对键：跳过而不是存半行，`product_key` 不会出现空串。
    assert keys and all(keys)


def test_live_row_with_empty_currency_does_not_drag_the_batch() -> None:
    """「币种为空」按字段判定，不按 `state`：`state=live` 也不能连坐整批。"""

    rows = _rows()
    victim = dict(next(row for row in rows if row["state"] == "live" and _has_currency(row)))
    broken = dict(victim, instId="ZXBROKEN-USDT", baseCcy="", quoteCcy="", instCategory="")
    live_rows = sum(1 for row in rows if row["state"] == "live" and _has_currency(row))

    report = sync_instruments(parse_instruments([*rows, broken]))

    assert report.total == len(rows) + 1
    assert report.inserted == live_rows
    assert _skip_ids(report) == [*_meta()["empty_currency_inst_ids"], "ZXBROKEN-USDT"]
    assert "baseCcy" in report.skipped[-1].reason

    stored, keys, symbols = _stored()
    assert stored == live_rows
    assert "ZXBROKEN-USDT" not in symbols
    assert all(keys)


def test_resyncing_the_same_snapshot_changes_nothing() -> None:
    refs = parse_instruments(_rows())

    first = sync_instruments(refs)
    after_first = _stored()
    second = sync_instruments(refs)
    after_second = _stored()

    assert (first.inserted, first.skipped) == (second.inserted, second.skipped)
    assert after_first == after_second


def test_live_count_matches_direct_query() -> None:
    """验收口径：库里 `inst_type='SPOT' and trading_status='live'` 的条数等于 live 行数。"""

    sync_instruments(parse_instruments(_rows()))

    with session_scope() as session:
        live = session.scalar(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.inst_type == "SPOT", Instrument.trading_status == "live")
        )

    assert live == _meta()["state_counts"]["live"]
