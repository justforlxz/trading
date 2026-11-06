"""OKX 标的清单 → `InstrumentRow`（归一化 + 分类）。"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.adapters.okx.client import OkxClient
from app.market.core.classification import classify
from app.ports.market_data import InstrumentRow

INSTRUMENTS_PATH = "/api/v5/public/instruments"

CATEGORY_ASSET_CLASS: dict[int, str] = {1: "crypto", 4: "commodity"}


def _decimal(value: Any) -> Decimal:
    """OKX 用字符串表示数值；空串按 0 处理（仅用于可选的数量字段）。"""

    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _ms_to_datetime(value: Any) -> datetime | None:
    if value in (None, "", "0"):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def symbol_of(inst_id: str, inst_family: str = "") -> str:
    """`AAPL-USDT-SWAP` → `AAPL`；优先用 instFamily 的前缀。"""

    source = inst_family or inst_id
    return source.split("-")[0].upper()


def classify_instrument(inst_category: int, symbol: str) -> tuple[str, str | None]:
    """按 instCategory 与维护表确定 asset_class / exchange。"""

    if inst_category in CATEGORY_ASSET_CLASS:
        return CATEGORY_ASSET_CLASS[inst_category], None
    classification = classify(symbol)
    return classification.asset_class, classification.exchange


def to_instrument_row(raw: dict[str, Any]) -> InstrumentRow:
    """把一条 OKX instruments 原始记录转成 DTO。"""

    inst_id = raw["instId"]
    inst_family = raw.get("instFamily") or raw.get("uly") or inst_id
    symbol = symbol_of(inst_id, inst_family)
    inst_category = int(raw.get("instCategory") or 0)
    asset_class, exchange = classify_instrument(inst_category, symbol)
    return InstrumentRow(
        inst_id=inst_id,
        inst_family=inst_family,
        uly=raw.get("uly") or "",
        inst_category=inst_category,
        asset_class=asset_class,
        exchange=exchange,
        ct_val=_decimal(raw.get("ctVal")),
        ct_val_ccy=raw.get("ctValCcy") or "",
        lot_sz=_decimal(raw.get("lotSz")),
        min_sz=_decimal(raw.get("minSz")),
        tick_sz=_decimal(raw.get("tickSz")),
        lever=_decimal(raw.get("lever")),
        state=raw.get("state") or "",
        rule_type=raw.get("ruleType") or "",
        list_time=_ms_to_datetime(raw.get("listTime")),
        raw=raw,
    )


class OkxInstrumentSource:
    """`InstrumentSource` 的 OKX 实现。"""

    def __init__(self, client: OkxClient) -> None:
        self._client = client

    async def fetch_instruments(self) -> list[InstrumentRow]:
        data = await self._client.get(INSTRUMENTS_PATH, {"instType": "SWAP"}, limiter="instruments")
        return [to_instrument_row(item) for item in data]
