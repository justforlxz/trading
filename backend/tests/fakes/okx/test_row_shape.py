"""工厂生成行与真实上游录制样本的形状一致性。

`tests/fixtures/okx/candles_XAAPL-USDT_1D.json` 与 `ticker_XAAPL-USDT.json`
是真实 OKX 响应的录制样本，作用只有一条：钉死 fake server 的行形状——
列数、列序、`confirm` 所在位置、倒序以及 1D 的 16:00 UTC 开盘边界。
上游一旦改列，这里先红。

夹具是测试专用录制样本，不是实时行情，也不参与价格计算。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tests.factories.candles import DAILY_OPEN_OFFSET_SECONDS, make_candle_rows, make_ticker_row
from tests.factories.instruments import FIXTURES_DIR

CANDLE_ROWS = "candles_XAAPL-USDT_1D.json"
TICKER_ROWS = "ticker_XAAPL-USDT.json"
SPOT_ID = "XAAPL-USDT"
COLUMN_COUNT = 9
CONFIRM_INDEX = 8


def _recorded(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))["response"]


def _generated_daily_rows(recorded: list[list[str]]) -> list[list[str]]:
    end_time = int(recorded[0][0]) // 1000
    return make_candle_rows(SPOT_ID, "1D", count=len(recorded), end_time=end_time)


def test_candle_rows_match_recorded_shape() -> None:
    payload = _recorded(CANDLE_ROWS)
    assert payload["code"] == "0"
    recorded = payload["data"]
    assert recorded

    end_time = int(recorded[0][0]) // 1000
    rows = make_candle_rows(SPOT_ID, "1D", count=len(recorded), end_time=end_time)

    assert len(rows) == len(recorded)
    assert [row[0] for row in rows] == [row[0] for row in recorded]
    for generated, upstream in zip(rows, recorded, strict=True):
        assert len(upstream) == COLUMN_COUNT
        assert len(generated) == COLUMN_COUNT
        assert all(isinstance(value, str) for value in generated)
        assert generated[CONFIRM_INDEX] == upstream[CONFIRM_INDEX]


def test_candle_rows_keep_incomplete_bar_newest_first() -> None:
    recorded = _recorded(CANDLE_ROWS)["data"]

    rows = _generated_daily_rows(recorded)

    assert rows[0][CONFIRM_INDEX] == recorded[0][CONFIRM_INDEX] == "0"
    assert {row[CONFIRM_INDEX] for row in rows[1:]} == {"1"}
    timestamps = [int(row[0]) for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


def test_daily_candle_rows_open_at_sixteen_utc() -> None:
    recorded = _recorded(CANDLE_ROWS)["data"]

    rows = _generated_daily_rows(recorded)

    for generated, upstream in zip(rows, recorded, strict=True):
        assert int(generated[0]) // 1000 % 86400 == DAILY_OPEN_OFFSET_SECONDS
        assert int(upstream[0]) // 1000 % 86400 == DAILY_OPEN_OFFSET_SECONDS


def test_ticker_row_matches_recorded_shape() -> None:
    payload = _recorded(TICKER_ROWS)
    assert payload["code"] == "0"
    upstream = payload["data"][0]

    row = make_ticker_row(SPOT_ID, ts=int(upstream["ts"]) // 1000)

    assert set(row) == set(upstream)
    assert all(isinstance(value, str) for value in row.values())
    assert Decimal(row["bidPx"]) < Decimal(row["last"]) < Decimal(row["askPx"])


@pytest.mark.parametrize("name", [CANDLE_ROWS, TICKER_ROWS])
def test_recorded_fixture_is_labelled_as_test_data(name: str) -> None:
    payload = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    assert payload["meta"]["kind"] == "test_fixture_recorded_response"
    assert "测试夹具" in payload["meta"]["purpose"]
    assert "不是实时行情" in payload["meta"]["purpose"]
