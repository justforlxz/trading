"""私有频道解析：账户与持仓字段必须与 B2 的快照结构一致。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.exchange import parse_account_snapshot_row, parse_exchange_position_row


def _account_row(**overrides: Any) -> dict[str, Any]:
    """OKX `account` 频道的一条官方结构推送。"""

    row: dict[str, Any] = {
        "totalEq": "100",
        "availEq": "80",
        "imr": "20",
        "upl": "1",
        "mgnRatio": "",
        "uTime": "1794284760000",
        "details": [
            {"ccy": "BTC", "eq": "1", "availEq": "1", "cashBal": "1", "upl": "0"},
            {"ccy": "USDT", "eq": "100", "availEq": "80", "cashBal": "50", "upl": "2"},
        ],
    }
    row.update(overrides)
    return row


def test_account_row_reads_account_level_fields_and_usdt_cash_from_details() -> None:
    snapshot = parse_account_snapshot_row(_account_row())

    assert snapshot.currency == "USDT"
    assert snapshot.equity == Decimal("100")
    assert snapshot.available_equity == Decimal("80")
    assert snapshot.cash_balance == Decimal("50")
    assert snapshot.unrealized_pnl == Decimal("1")
    assert snapshot.used_margin == Decimal("20")
    assert snapshot.available_margin == Decimal("80")
    assert snapshot.margin_ratio == Decimal("0.2")


def test_account_row_without_available_equity_subtracts_used_margin() -> None:
    row = _account_row(availEq="", imr="25")
    row["details"][1]["availEq"] = ""

    snapshot = parse_account_snapshot_row(row)

    assert snapshot.available_equity == Decimal("75")
    assert snapshot.margin_ratio == Decimal("0.25")


def test_account_row_does_not_use_another_currency_cash_balance() -> None:
    row = _account_row()
    row["details"] = [item for item in row["details"] if item["ccy"] != "USDT"]

    snapshot = parse_account_snapshot_row(row)

    assert snapshot.cash_balance == Decimal("0")


def test_position_row_keeps_the_same_fields_as_the_rest_snapshot() -> None:
    item = parse_exchange_position_row(
        {
            "instId": "AAPL-USDT-SWAP",
            "posId": "123",
            "pos": "-2",
            "posSide": "net",
            "avgPx": "100",
            "markPx": "90",
            "upl": "20",
            "uplRatio": "0.1",
            "lever": "3",
            "mgnMode": "cross",
            "liqPx": "150",
            "margin": "60",
        }
    )

    assert item.pos_id == "123"
    assert item.inst_id == "AAPL-USDT-SWAP"
    assert item.pos_side == "short"
    assert item.size == Decimal("2")
    assert item.avg_px == Decimal("100")
    assert item.mark_px == Decimal("90")
    assert item.upl == Decimal("20")
    assert item.upl_ratio == Decimal("0.1")
    assert item.lever == Decimal("3")
    assert item.mgn_mode == "cross"
    assert item.liq_px == Decimal("150")
    assert item.margin == Decimal("60")


def test_zero_position_is_kept_for_the_caller_to_filter() -> None:
    item = parse_exchange_position_row({"instId": "AAPL-USDT-SWAP", "pos": "0"})

    assert item.size == 0
