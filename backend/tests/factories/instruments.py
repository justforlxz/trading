"""标的清单夹具工厂。

数据来源封闭：只有 `tests/fixtures/okx/instruments_2026-11-10.json`
这一份冻结快照，以及本模块构造的单行样本。快照是测试夹具，不是实时行情。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core import InstrumentRef

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "okx"
INSTRUMENT_SNAPSHOT_PATH = FIXTURES_DIR / "instruments_2026-11-10.json"
SAMPLE_LIST_TIME = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)

# 快照自带的计数，用来防止夹具被无声改动导致下游验收数字漂移。
EXPECTED_COUNTS: dict[str, int] = {
    "total": 429,
    "spot": 199,
    "swap": 230,
    "spot_product_keys_with_swap": 169,
}


def load_snapshot() -> dict[str, Any]:
    """读取整份快照文档（含 meta）。"""

    with INSTRUMENT_SNAPSHOT_PATH.open(encoding="utf-8") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


def load_instruments() -> list[dict[str, Any]]:
    """读取快照里的 429 行标的，并校验计数没有被改动。"""

    document = load_snapshot()
    meta = document["meta"]
    counts = meta["counts"]
    if counts != EXPECTED_COUNTS:
        raise AssertionError(f"夹具计数漂移:{counts} != {EXPECTED_COUNTS}")
    rows: list[dict[str, Any]] = document["instruments"]
    if len(rows) != EXPECTED_COUNTS["total"]:
        raise AssertionError(f"夹具行数漂移:{len(rows)} != {EXPECTED_COUNTS['total']}")
    return rows


def make_instrument_row(**overrides: Any) -> dict[str, Any]:
    """构造单行标的样本，默认值模仿 OKX 代币化股票现货。"""

    row: dict[str, Any] = {
        "instType": "SPOT",
        "instId": "XAAPL-USDT",
        "instCategory": "3",
        "state": "live",
        "baseCcy": "XAAPL",
        "quoteCcy": "USDT",
        "ctValCcy": "",
        "uly": "",
        "instFamily": "",
        "tickSz": "0.01",
        "lotSz": "0.00001",
        "minSz": "0.01",
        "listTime": "1784181600000",
        "ctVal": "",
        "ctMult": "",
        "ctType": "",
        "lever": "10",
        "settleCcy": "",
        "openType": "pre_quote",
        "ruleType": "normal",
        "category": "1",
        "alias": "",
    }
    row.update(overrides)
    return row


def make_ref(**overrides: Any) -> InstrumentRef:
    """构造一条上游标的中立快照，默认代币化股票现货 `XAAPL-USDT`。"""

    defaults: dict[str, Any] = {
        "inst_id": "XAAPL-USDT",
        "inst_type": "SPOT",
        "base_ccy": "XAAPL",
        "quote_ccy": "USDT",
        "state": "live",
        "inst_category": "3",
        "tick_size": Decimal("0.01"),
        "lot_size": Decimal("0.00001"),
        "min_size": Decimal("0.01"),
        "list_time": SAMPLE_LIST_TIME,
    }
    defaults.update(overrides)
    return InstrumentRef(**defaults)


def make_swap_ref(**overrides: Any) -> InstrumentRef:
    """构造一条永续快照，默认 `AAPL-USDT-SWAP`（与 `make_ref` 同产品）。"""

    defaults: dict[str, Any] = {
        "inst_id": "AAPL-USDT-SWAP",
        "inst_type": "SWAP",
        "base_ccy": "",
        "quote_ccy": "",
        "state": "live",
        "inst_category": "3",
        "tick_size": Decimal("0.01"),
        "lot_size": Decimal("0.01"),
        "min_size": Decimal("0.01"),
        "list_time": SAMPLE_LIST_TIME,
        "ct_val_ccy": "AAPL",
        "settle_ccy": "USDT",
        "ct_val": Decimal("1"),
        "ct_mult": Decimal("1"),
        "ct_type": "linear",
        "max_lever": Decimal("20"),
    }
    defaults.update(overrides)
    return InstrumentRef(**defaults)
