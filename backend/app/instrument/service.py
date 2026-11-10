"""标的同步与查询：把上游快照落库，并按产品取回两种形态。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.core import InstrumentRef, ValidationError
from app.db import session_scope
from app.instrument.model import SPOT, SWAP, Instrument, InstrumentPair, build_instrument

__all__ = ["get_instrument_pair", "list_instruments", "sync_instruments"]

# 现货可能有多个报价（USDT / USDC）；默认配对与永续同报价的那一档。
DEFAULT_QUOTE_CURRENCY = "USDT"


def sync_instruments(refs: Sequence[InstrumentRef]) -> int:
    """按 `symbol`（交易所 instId）写入或更新，返回处理的条数。

    以 `symbol` 为主键 upsert：同一份快照重复同步只会更新字段，不会新增行，
    因此可以安全地反复执行。
    """

    instruments = [build_instrument(ref) for ref in refs]
    with session_scope() as session:
        for instrument in instruments:
            session.merge(instrument)
    return len(instruments)


def list_instruments() -> list[Instrument]:
    """全部标的，按 `symbol` 排序。"""

    with session_scope() as session:
        return list(session.scalars(select(Instrument).order_by(Instrument.symbol)))


def get_instrument_pair(product_key: str) -> InstrumentPair:
    """按产品键取现货与永续；某一形态不存在时该侧为 `None`。

    现货同时挂了 USDT / USDC 两个报价时，优先返回与永续同报价的现货；没有
    永续则优先 USDT。找不到任何标的时抛 `ValidationError`，不返回空壳。
    """

    key = product_key.strip().upper()
    if not key:
        raise ValidationError("产品键不能为空")

    with session_scope() as session:
        rows = list(session.scalars(select(Instrument).where(Instrument.product_key == key)))
    if not rows:
        raise ValidationError(f"未找到产品 {key} 的标的")

    swap = next((row for row in rows if row.inst_type == SWAP), None)
    spots = [row for row in rows if row.inst_type == SPOT]
    return InstrumentPair(product_key=key, spot=_pick_spot(spots, swap), swap=swap)


def _pick_spot(spots: list[Instrument], swap: Instrument | None) -> Instrument | None:
    if not spots:
        return None
    preferred = swap.quote_currency if swap is not None else DEFAULT_QUOTE_CURRENCY
    ordered = sorted(spots, key=lambda row: row.symbol)
    for spot in ordered:
        if spot.quote_currency == preferred:
            return spot
    return ordered[0]
