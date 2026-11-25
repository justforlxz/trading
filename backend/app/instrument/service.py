"""标的同步与查询：把上游快照落库，并按产品取回两种形态。

两种形态（`XAAPL-USDT` 与 `AAPL-USDT-SWAP`）只经 `product_key` 关联：解析入口
`resolve_instrument` 不做任何字符串推导——不去 `X` 前缀，也不拼 `-USDT-SWAP`。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, any_, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY
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
    unstorable_reason,
)

__all__ = [
    "DEFAULT_QUOTE_CURRENCY",
    "SyncReport",
    "SyncSkip",
    "TradableRef",
    "display_symbol",
    "get_instrument",
    "get_instrument_pair",
    "get_instruments",
    "list_instruments",
    "list_tradable",
    "list_tradable_refs",
    "resolve_instrument",
    "sync_instruments",
]

# 现货可能有多个报价（USDT / USDC）；默认配对与永续同报价的那一档。
DEFAULT_QUOTE_CURRENCY = "USDT"
# 上游 `state` 里唯一允许下单的取值。
LIVE_STATUS = "live"


@dataclass(frozen=True, slots=True)
class SyncSkip:
    """一条没有入库的标的，以及为什么。"""

    inst_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SyncReport:
    """一次同步的结果：入库条数与逐条跳过记录，两者之和等于输入行数。"""

    inserted: int
    skipped: tuple[SyncSkip, ...]

    @property
    def total(self) -> int:
        return self.inserted + len(self.skipped)


def sync_instruments(refs: Sequence[InstrumentRef]) -> SyncReport:
    """按 `symbol`（交易所 instId）写入或更新，返回入库与跳过的明细。

    单行不合法只跳过这一行并记下原因，不影响同批其余标的：真实现货快照里有上游
    还没下发币种的 preopen 行，一行空币种都不许把整批 1216 条 `live` 标的一起回滚。

    以 `symbol` 为主键 upsert：同一份快照重复同步只会更新字段，不会新增行，
    因此可以安全地反复执行。
    """

    instruments: list[Instrument] = []
    skipped: list[SyncSkip] = []
    for ref in refs:
        try:
            reason = unstorable_reason(ref)
            if reason is not None:
                skipped.append(SyncSkip(ref.inst_id, reason))
                continue
            instruments.append(build_instrument(ref))
        except ValidationError as exc:
            skipped.append(SyncSkip(ref.inst_id, str(exc)))

    with session_scope() as session:
        for instrument in instruments:
            session.merge(instrument)
    return SyncReport(inserted=len(instruments), skipped=tuple(skipped))


def list_instruments() -> list[Instrument]:
    """全部标的，按 `symbol` 排序。"""

    with session_scope() as session:
        return list(session.scalars(select(Instrument).order_by(Instrument.symbol)))


def get_instrument(symbol: str) -> Instrument | None:
    """按交易所 `instId` 取一行标的；没有时返回 `None`，由调用方决定错误措辞。"""

    raw = _clean(symbol)
    if not raw:
        return None
    with session_scope() as session:
        return session.scalar(select(Instrument).where(Instrument.symbol == raw))


def get_instruments(symbols: Iterable[str]) -> dict[str, Instrument]:
    """按一批 `instId` 取标的；表里没有的标的不出现在结果里。

    与逐个调用 `get_instrument` 同一读法（去空白、转大写），只是把一次一条改成一条
    取完：持仓、自选按批读标的元数据时不再按行发语句。结果按调用方传进来的那个写法
    作键，`row.inst_id` 这类原始值可以直接回查，不用再自己规范化一遍。
    """

    cleaned = {symbol: _clean(symbol) for symbol in dict.fromkeys(symbols)}
    wanted = sorted({value for value in cleaned.values() if value})
    if not wanted:
        return {}
    # 标的清单走绑定参数 `text[]`：写进 `IN (...)` 会让语句文本随标的数膨胀，传数组
    # 只多一个参数（与 `app.market.sync` 的批量取数同一写法；那一层依赖本模块，
    # 反过来引用会造成循环依赖，所以这里各写一行）。
    statement = select(Instrument).where(
        Instrument.symbol == any_(bindparam("symbols", type_=ARRAY(String(64))))
    )
    with session_scope() as session:
        found = {row.symbol: row for row in session.scalars(statement, {"symbols": wanted})}
    return {symbol: found[value] for symbol, value in cleaned.items() if value in found}


def _clean(symbol: str) -> str:
    """`instId` 的读入口径：去首尾空白、转大写。"""

    return symbol.strip().upper()


def display_symbol(row: Instrument) -> str:
    """给人看的标的名：`产品键-报价币`，例如 `AAPL-USDT`。

    两种形态（`XAAPL-USDT` 与 `AAPL-USDT-SWAP`）在这里统一成同一个展示名，
    与产品键和报价币的配对关系只由标的模块维护，其他模块不拼字符串。
    """

    return f"{row.product_key}-{row.quote_currency}"


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


@dataclass(frozen=True, slots=True)
class TradableRef:
    """可交易标的的精简视图：只有横截面按标的选行情来源要用的三列。

    批量横截面读取（`app.market` 的市场总览）只需要「标识、类别、资产」，拿到完整的
    `Instrument` 实体等于为 1797 行各造一个对象却只用其中三个字段。这里只带三列，
    筛选规则仍与 `list_tradable` 共用 `_tradable_criteria`，不另立一套。
    """

    symbol: str
    inst_type: str
    asset_type: str


def _tradable_criteria(inst_type: str | None) -> tuple[Any, ...]:
    """可交易标的的筛选规则：唯一出处，`list_tradable` 与 `list_tradable_refs` 共用。"""

    criteria: list[Any] = [Instrument.trading_status == LIVE_STATUS]
    if inst_type is not None:
        criteria.append(Instrument.inst_type == _normalize_inst_type(inst_type))
    return tuple(criteria)


def list_tradable(inst_type: str | None = None) -> list[Instrument]:
    """按类别返回可交易标的（`state == live`），不按资产类别过滤。

    加密资产与代币化股票同属一个类别，这里不再按资产层筛选。不传类别时返回两类合起来
    的清单——批量回测的「全部可交易」就是这个范围；传了就只取那一类。顺序按 `symbol`
    固定，同一份库两次调用得到同一序列。
    """

    statement = select(Instrument).where(*_tradable_criteria(inst_type))
    with session_scope() as session:
        return list(session.scalars(statement.order_by(Instrument.symbol)))


def list_tradable_refs(inst_type: str | None = None) -> list[TradableRef]:
    """与 `list_tradable` 同一批标的、同一顺序，只取三列；供批量横截面读取用。

    返回的标识集合与顺序必须与 `list_tradable` 逐项相同（由测试钉住）：调用方按标的
    选行情来源，少一个标的就会少算一家涨跌。
    """

    statement = select(Instrument.symbol, Instrument.inst_type, Instrument.asset_type).where(
        *_tradable_criteria(inst_type)
    )
    with session_scope() as session:
        return [
            TradableRef(symbol=symbol, inst_type=kind, asset_type=asset)
            for symbol, kind, asset in session.execute(statement.order_by(Instrument.symbol))
        ]


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
