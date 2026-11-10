"""上游标的元数据 → 中立 `InstrumentRef`。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import InstrumentRef, utc_from_millis
from app.exchange.errors import ExchangeError

__all__ = ["parse_instruments"]

# 永续行的 `baseCcy` / `quoteCcy` 是空串：标的币种写在 `ctValCcy`，结算币种写在
# `settleCcy`。按类别取字段，不从 `instId` 拆字符串推断。
_CURRENCY_FIELDS: dict[str, tuple[str, str]] = {
    "SPOT": ("baseCcy", "quoteCcy"),
    "SWAP": ("ctValCcy", "settleCcy"),
}


def parse_instruments(rows: list[Any]) -> list[InstrumentRef]:
    """逐条解析上游标的元数据；字段缺失或数值非法时抛 `ExchangeError`。

    尚未开盘的标的会把精度字段留空，这类字段按「未知」（None）处理，不让单条
    preopen 记录拖垮整批标的列表。
    """

    return [_parse_instrument(row) for row in rows]


def _parse_instrument(row: Any) -> InstrumentRef:
    if not isinstance(row, dict):
        raise ExchangeError("标的元数据结构异常")
    try:
        inst_type = str(row["instType"])
        base_field, quote_field = _currency_fields(inst_type)
        return InstrumentRef(
            inst_id=str(row["instId"]),
            inst_type=inst_type,
            base_ccy=str(row[base_field]),
            quote_ccy=str(row[quote_field]),
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


def _currency_fields(inst_type: str) -> tuple[str, str]:
    """类别 → (标的币种字段, 报价或结算币种字段)。"""

    try:
        return _CURRENCY_FIELDS[inst_type]
    except KeyError:
        raise ExchangeError(f"标的类别没有币种字段映射:{inst_type!r}") from None


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
