"""标的同步与查询：把上游快照落库，并按产品取回两种形态。

两种形态（`XAAPL-USDT` 与 `AAPL-USDT-SWAP`）只经 `product_key` 关联：解析入口
`resolve_instrument` 不做任何字符串推导——不去 `X` 前缀，也不拼 `-USDT-SWAP`。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import InstrumentRef, ValidationError
from app.db import session_scope
from app.instrument.model import (
    INST_TYPES,
    SPOT,
    SWAP,
    Instrument,
    InstrumentPair,
    build_instrument,
)

__all__ = [
    "get_instrument_pair",
    "list_instruments",
    "list_tradable",
    "resolve_instrument",
    "sync_instruments",
]

# 现货可能有多个报价（USDT / USDC）；默认配对与永续同报价的那一档。
DEFAULT_QUOTE_CURRENCY = "USDT"
# 上游 `state` 里唯一允许下单的取值。
LIVE_STATUS = "live"


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

    key = _normalize_key(product_key, "产品键")
    with session_scope() as session:
        pair = _load_pair(session, key)
    if pair is None:
        raise ValidationError(f"未找到产品 {key} 的标的")
    return pair


def resolve_instrument(query: str, inst_type: str) -> Instrument:
    """把用户给的代码解析成指定形态的标的；找不到就报错，不猜。

    `query` 接受产品键（`AAPL`）或任一形态的交易所标识（`XAAPL-USDT`、
    `AAPL-USDT-SWAP`），大小写不敏感。产品键只从库里已有的行取：先按 `symbol`
    精确匹配，没命中再当成产品键查。两种形态的关联一律走 `product_key`。
    """

    wanted = _normalize_inst_type(inst_type)
    raw = _normalize_key(query, "标的查询")

    with session_scope() as session:
        hit = session.scalar(select(Instrument).where(Instrument.symbol == raw))
        pair = _load_pair(session, hit.product_key if hit is not None else raw)
    if pair is None:
        raise ValidationError(f"未找到标的 {raw}")

    target = pair.swap if wanted == SWAP else pair.spot
    if target is None:
        raise ValidationError(f"产品 {pair.product_key} 没有 {wanted} 形态的标的")
    return target


def list_tradable(inst_type: str) -> list[Instrument]:
    """按类别返回可交易标的（`state == live`），不按资产类别过滤。

    加密资产与代币化股票同属一个类别，这里不再按资产层筛选；顺序按 `symbol`
    固定，同一份库两次调用得到同一序列。
    """

    wanted = _normalize_inst_type(inst_type)
    with session_scope() as session:
        rows = session.scalars(
            select(Instrument)
            .where(Instrument.inst_type == wanted, Instrument.trading_status == LIVE_STATUS)
            .order_by(Instrument.symbol)
        )
        return list(rows)


def _pick_spot(spots: list[Instrument], swap: Instrument | None) -> Instrument | None:
    if not spots:
        return None
    preferred = swap.quote_currency if swap is not None else DEFAULT_QUOTE_CURRENCY
    ordered = sorted(spots, key=lambda row: row.symbol)
    for spot in ordered:
        if spot.quote_currency == preferred:
            return spot
    return ordered[0]


def _load_pair(session: Session, product_key: str) -> InstrumentPair | None:
    """按产品键取回该产品的全部形态；库里一行都没有时返回 `None`。

    调用方自己决定「没找到」的措辞与错误类型，因此这里不抛异常。
    """

    rows = list(session.scalars(select(Instrument).where(Instrument.product_key == product_key)))
    if not rows:
        return None
    swap = next((row for row in rows if row.inst_type == SWAP), None)
    spots = [row for row in rows if row.inst_type == SPOT]
    return InstrumentPair(product_key=product_key, spot=_pick_spot(spots, swap), swap=swap)


def _normalize_key(raw: str, label: str) -> str:
    """去掉首尾空白并统一大写；空值按参数错误拒绝。"""

    key = raw.strip().upper()
    if not key:
        raise ValidationError(f"{label}不能为空")
    return key


def _normalize_inst_type(inst_type: str) -> str:
    """归一化标的类别；未支持的类别直接报错，不返回默认值。"""

    name = inst_type.strip().upper()
    if name not in INST_TYPES:
        raise ValidationError(f"标的类别 {inst_type!r} 不在支持范围:{sorted(INST_TYPES)}")
    return name
