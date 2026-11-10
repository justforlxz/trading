"""上游标的元数据 → 中立 `InstrumentRef`。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import InstrumentRef, utc_from_millis
from app.exchange.errors import ExchangeError

__all__ = ["parse_instruments"]


def parse_instruments(rows: list[Any]) -> list[InstrumentRef]:
    """逐条解析上游标的元数据；字段缺失或数值非法时抛 `ExchangeError`。

    尚未开盘的标的会把精度字段留空，这类字段按「未知」（None）处理，不让单条
    preopen 记录拖垮整批现货列表。
    """

    return [_parse_instrument(row) for row in rows]


def _parse_instrument(row: Any) -> InstrumentRef:
    if not isinstance(row, dict):
        raise ExchangeError("标的元数据结构异常")
    try:
        return InstrumentRef(
            inst_id=str(row["instId"]),
            inst_type=str(row["instType"]),
            base_ccy=str(row["baseCcy"]),
            quote_ccy=str(row["quoteCcy"]),
            state=str(row["state"]),
            inst_category=str(row.get("instCategory") or ""),
            tick_size=_decimal_or_none(row.get("tickSz")),
            lot_size=_decimal_or_none(row.get("lotSz")),
            min_size=_decimal_or_none(row.get("minSz")),
            list_time=utc_from_millis(row["listTime"]) if row.get("listTime") else None,
            ct_val_ccy=str(row.get("ctValCcy") or ""),
            settle_ccy=str(row.get("settleCcy") or ""),
            ct_val=_decimal_or_none(row.get("ctVal")),
            ct_mult=_decimal_or_none(row.get("ctMult")),
            ct_type=str(row.get("ctType") or ""),
            max_lever=_decimal_or_none(row.get("lever")),
        )
    except KeyError as exc:
        raise ExchangeError(f"标的元数据缺少字段:{exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ExchangeError(f"标的元数据时间戳非法:{row.get('listTime')!r}") from exc


def _decimal_or_none(value: Any) -> Decimal | None:
    """上游未下发（缺失或空串）的精度字段记为 None，其余按数值严格解析。"""

    if value is None or str(value).strip() == "":
        return None
    return _decimal(value)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExchangeError(f"标的元数据数值非法:{value!r}") from exc
