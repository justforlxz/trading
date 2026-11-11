"""机会发现的编排：取数 → 评分 → 落库 → 读回；以及机会状态的唯一状态机。

写侧只做两件事：按类别取标的与行情（来源仍由 `app.market` 的「资产时段 × 资产类别」
规则决定，本模块不另定一套），把 `app.opportunity.detect` 的候选记录成一行。同一
`as_of` 与同一份输入重复执行得到同一批 `opportunity_id`，已存在的行不会被覆盖——
状态是人工审核的结论，重跑检测不许把它抹掉。

读侧只读库：列表、详情与状态流转。

状态机只有一条合法路径：`new → reviewed → adopted | rejected`，以及
`new | reviewed → expired`。非法转移一律抛 `ValidationError`，这里不做任何兜底，
也不把状态错误吞成「忽略本次变更」。域层用 `None` 表示「没有这条机会」，由 API 层
翻译成 404。

检测本身是一个服务入口，没有对应的 HTTP 端点：契约只暴露已落库的机会（列表、
详情、状态变更），跑检测的时机由上层调度决定。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy import func, select

from app.core import Bar, DataUnavailable, ValidationError
from app.db import session_scope
from app.instrument import Instrument, get_instrument_pair, list_tradable
from app.market import asset_session, load_candles, pearson, primary_source
from app.opportunity.detect import (
    WINDOW_BARS,
    Candidate,
    Leg,
    Observation,
    market_candidates,
    target_candidate,
)
from app.opportunity.model import OpportunityRow

__all__ = [
    "ALLOWED_TRANSITIONS",
    "BAR",
    "MODES",
    "STATUSES",
    "OpportunityRecord",
    "detect_opportunities",
    "get_opportunity",
    "list_opportunities",
    "set_status",
    "transition",
]

# 检测使用的周期：机会是给波段组合用的，日线足够，也与 T2.3 / T2.5 同口径。
BAR = "1d"

# 机会模式：与契约的 `OpportunityMode` 同值。
MODES = ("target", "market")

STATUS_NEW = "new"
STATUS_REVIEWED = "reviewed"
STATUS_ADOPTED = "adopted"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"

STATUSES = (STATUS_NEW, STATUS_REVIEWED, STATUS_ADOPTED, STATUS_REJECTED, STATUS_EXPIRED)

# 唯一真源：当前状态 → 允许进入的下一状态。终态没有任何出边。
ALLOWED_TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        STATUS_NEW: frozenset({STATUS_REVIEWED, STATUS_EXPIRED}),
        STATUS_REVIEWED: frozenset({STATUS_ADOPTED, STATUS_REJECTED, STATUS_EXPIRED}),
        STATUS_ADOPTED: frozenset(),
        STATUS_REJECTED: frozenset(),
        STATUS_EXPIRED: frozenset(),
    }
)

# 标的类别：与契约的 `InstType` 同值。两类标的的交易时段不同，逐类统计、不混合。
INST_TYPES = ("SPOT", "SWAP")


@dataclass(frozen=True, slots=True)
class OpportunityRecord:
    """一条已落库的机会：腿已从 JSON 还原，`evidence` 保持库里的原文。"""

    opportunity_id: str
    mode: str
    anchor_product_key: str | None
    as_of: datetime
    score: Decimal
    legs: tuple[Leg, ...]
    evidence: str
    status: str


def detect_opportunities(
    as_of: datetime | None = None,
    bar: str = BAR,
    *,
    anchor_product_key: str | None = None,
) -> tuple[OpportunityRecord, ...]:
    """跑一次检测并落库，返回这次涉及的记录（含此前已存在的同一批）。

    给锚点是目标驱动（`anchor_product_key` 必须能解析到标的），不给锚点是市场驱动
    （按类别扫描全部可交易标的）。`as_of` 缺省取当前时刻；给出时必须带时区，且
    之后的 K 线一根都不读。
    """

    moment = _moment(as_of)
    if anchor_product_key is not None:
        anchor = _anchor_sample(anchor_product_key, bar, moment)
        peers = _samples(_universe(anchor.inst_type), bar, moment)
        candidate = target_candidate(anchor, peers, _correlations(anchor, peers), as_of=moment)
        candidates: tuple[Candidate, ...] = () if candidate is None else (candidate,)
    else:
        candidates = market_candidates(
            {inst_type: _samples(_universe(inst_type), bar, moment) for inst_type in INST_TYPES},
            as_of=moment,
        )
    return _persist(candidates)


def list_opportunities(
    *,
    mode: str | None = None,
    anchor_product_key: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> tuple[tuple[OpportunityRecord, ...], int]:
    """按过滤条件列出机会，返回（本页记录，符合条件的总条数）。

    排序是「判定时刻倒序、分数倒序、标识升序」：同一份库两次读取顺序一致，分页不会
    因为数据库返回顺序漂移。`total` 与 `limit` 无关，是过滤条件下的全部条数。
    """

    _require_mode(mode)
    _require_status(status)
    if limit < 1:
        raise ValidationError(f"条数上限必须是正整数:{limit}")

    conditions = []
    if mode is not None:
        conditions.append(OpportunityRow.mode == mode)
    if anchor_product_key is not None:
        key = anchor_product_key.strip().upper()
        conditions.append(OpportunityRow.anchor_product_key == key)
    if status is not None:
        conditions.append(OpportunityRow.status == status)

    statement = (
        select(OpportunityRow)
        .where(*conditions)
        .order_by(
            OpportunityRow.as_of.desc(),
            OpportunityRow.score.desc(),
            OpportunityRow.opportunity_id,
        )
        .limit(limit)
    )
    with session_scope() as session:
        rows = list(session.scalars(statement))
        counted = select(func.count()).select_from(OpportunityRow).where(*conditions)
        total = session.scalar(counted)
    return tuple(_record(row) for row in rows), total or 0


def get_opportunity(opportunity_id: str) -> OpportunityRecord | None:
    """按标识取一条机会；不存在返回 `None`，由调用方决定怎么报错。"""

    with session_scope() as session:
        row = session.get(OpportunityRow, opportunity_id)
        return None if row is None else _record(row)


def set_status(opportunity_id: str, target: str) -> OpportunityRecord | None:
    """把一条机会推进到 `target` 状态；机会不存在返回 `None`。

    非法转移抛 `ValidationError`（`transition` 的唯一出口），不静默忽略。
    """

    _require_status(target)
    with session_scope() as session:
        row = session.get(OpportunityRow, opportunity_id)
        if row is None:
            return None
        row.status = transition(row.status, target)
        return _record(row)


def transition(current: str, target: str) -> str:
    """校验一次状态流转并返回目标状态；不合法就报错，不做任何兜底。"""

    _require_status(current)
    _require_status(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValidationError(f"机会状态不能从 {current} 变为 {target}")
    return target


def _moment(as_of: datetime | None) -> datetime:
    """判定时刻：缺省取当前时刻；给出的时刻必须带时区，并收敛到秒。"""

    moment = datetime.now(tz=UTC) if as_of is None else as_of
    if moment.tzinfo is None:
        raise ValidationError("机会检测的 as_of 必须带时区")
    return moment.astimezone(UTC).replace(microsecond=0)


def _require_mode(mode: str | None) -> None:
    if mode is not None and mode not in MODES:
        raise ValidationError(f"未知的机会模式 {mode!r}; 支持: {', '.join(MODES)}")


def _require_status(status: str | None) -> None:
    if status is not None and status not in STATUSES:
        raise ValidationError(f"未知的机会状态 {status!r}; 支持: {', '.join(STATUSES)}")


def _universe(inst_type: str) -> list[Instrument]:
    """某个类别的全部可交易标的，一个产品只出一条腿。

    可交易集合由 `list_tradable` 按状态筛；同一产品可能挂了多个报价（`XAAPL-USDT`
    与 `XAAPL-USDC`），挑哪一条由 `app.instrument` 的配对规则决定，本模块不再自己
    按符号排序挑一行——两份规则迟早分叉。类别不是硬编码的分支：配对结果的哪一侧
    属于本次扫描的类别，由那一侧自己的 `inst_type` 说明。
    """

    keys = sorted({row.product_key for row in list_tradable(inst_type)})
    universe: list[Instrument] = []
    for key in keys:
        pair = get_instrument_pair(key)
        legs = [
            row for row in (pair.spot, pair.swap) if row is not None and row.inst_type == inst_type
        ]
        if legs:
            universe.append(legs[0])
    return universe


def _anchor_sample(product_key: str, bar: str, as_of: datetime) -> Observation:
    """锚点自身的样本：优先永续（全天候有行情，也是执行的主形态），没有就用现货。"""

    key = product_key.strip().upper()
    if not key:
        raise ValidationError("锚点不能为空")
    pair = get_instrument_pair(key)
    leg = pair.swap or pair.spot
    if leg is None:
        raise ValidationError(f"产品 {key} 既没有现货也没有永续")
    candidates = _samples([leg], bar, as_of)
    if not candidates:
        raise DataUnavailable(f"锚点 {key} 在 {as_of.isoformat()} 之前没有足够的 K 线")
    return candidates[0]


def _samples(
    instruments: Sequence[Instrument], bar: str, as_of: datetime
) -> tuple[Observation, ...]:
    """每个标的在 `as_of`（含）之前、其有效来源下最近 `WINDOW_BARS + 1` 根 K 线。

    来源按「资产时段 × 资产类别」解析（与市场总览、当前行情同一条规则）：代币化
    股票在美股交易时段读代理行情，休市时段与加密资产读 OKX 行情。不足两根 K 线的
    标的没有方向，不进样本——不补造、也不当成「不变」。
    """

    end = as_of + timedelta(seconds=1)
    observations: list[Observation] = []
    for instrument in instruments:
        state = asset_session(instrument.asset_type, as_of, inst_type=instrument.inst_type)
        source = primary_source(state, instrument.asset_type, instrument.inst_type)
        bars = load_candles(instrument.symbol, bar, end=end, source=source)
        if len(bars) < 2:
            continue
        observations.append(
            Observation(
                product_key=instrument.product_key,
                inst_id=instrument.symbol,
                inst_type=instrument.inst_type,
                source=source,
                bars=tuple(bars[-(WINDOW_BARS + 1) :]),
            )
        )
    return tuple(observations)


def _correlations(anchor: Observation, peers: Sequence[Observation]) -> dict[str, float | None]:
    """每个邻居与锚点的相关系数；来源不同的标的不参与比较。

    不同来源的 K 线无法用同一个时间轴对齐（代理日线开在美东 09:30、OKX 日线开在
    16:00 UTC），把两条不同来源的序列硬算一个系数只会得到一个假的邻居。
    """

    coefficients: dict[str, float | None] = {}
    for peer in peers:
        if peer.product_key == anchor.product_key or peer.source != anchor.source:
            continue
        left, right = _aligned_closes(anchor.bars, peer.bars)
        coefficients[peer.product_key] = pearson(left, right)
    return coefficients


def _aligned_closes(left: Sequence[Bar], right: Sequence[Bar]) -> tuple[list[float], list[float]]:
    """按 `open_time` 取交集后、最近 `WINDOW_BARS` 个样本的两条收盘价序列。"""

    left_by_time = {candle.open_time: float(candle.close) for candle in left}
    right_by_time = {candle.open_time: float(candle.close) for candle in right}
    common = sorted(left_by_time.keys() & right_by_time.keys())[-WINDOW_BARS:]
    return (
        [left_by_time[moment] for moment in common],
        [right_by_time[moment] for moment in common],
    )


def _persist(candidates: Sequence[Candidate]) -> tuple[OpportunityRecord, ...]:
    """把候选写库：标识已存在就原样保留（连同状态），不覆盖、不追加副本。"""

    records: list[OpportunityRecord] = []
    with session_scope() as session:
        for candidate in candidates:
            opportunity_id = _opportunity_id(candidate)
            row = session.get(OpportunityRow, opportunity_id)
            if row is None:
                row = OpportunityRow(
                    opportunity_id=opportunity_id,
                    mode=candidate.mode,
                    anchor_product_key=candidate.anchor_product_key,
                    as_of=candidate.as_of,
                    score=candidate.score,
                    legs=_legs_json(candidate.legs),
                    evidence=_evidence_json(candidate.evidence),
                    status=STATUS_NEW,
                )
                session.add(row)
            records.append(_record(row))
    return tuple(records)


def _opportunity_id(candidate: Candidate) -> str:
    """标识由内容派生：模式、锚点、判定时刻与腿一致时标识一致。

    腿的列表已经在 `detect` 里排过序，因此同一份输入得到同一个标识；这与「同一
    `as_of` 与同一输入重复执行产生完全相同的标识集合」是同一条性质。
    """

    payload = json.dumps(
        {
            "mode": candidate.mode,
            "anchor_product_key": candidate.anchor_product_key,
            "as_of": candidate.as_of.isoformat(),
            "legs": [[leg.inst_id, leg.direction] for leg in candidate.legs],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "opp_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _legs_json(legs: Sequence[Leg]) -> str:
    """腿 → JSON 文本：键排序、无多余空白，同一批腿两次序列化逐字相同。"""

    return json.dumps(
        [
            {
                "inst_id": leg.inst_id,
                "inst_type": leg.inst_type,
                "product_key": leg.product_key,
                "direction": leg.direction,
                "score": format(leg.score, "f"),
            }
            for leg in legs
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _evidence_json(evidence: Mapping[str, object]) -> str:
    """判定依据 → JSON 文本；数值在 `detect` 里已按同一精度收敛。"""

    return json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _record(row: OpportunityRow) -> OpportunityRecord:
    """库里的行 → 域记录；腿从 JSON 还原，`evidence` 保持原文透传。"""

    return OpportunityRecord(
        opportunity_id=row.opportunity_id,
        mode=row.mode,
        anchor_product_key=row.anchor_product_key,
        as_of=row.as_of,
        score=row.score,
        legs=_legs_from_json(row.legs),
        evidence=row.evidence,
        status=row.status,
    )


def _legs_from_json(text: str) -> tuple[Leg, ...]:
    """腿的 JSON 文本 → 值对象；形状不对说明库里被写脏了，直接报错。"""

    legs = []
    for item in json.loads(text):
        legs.append(
            Leg(
                inst_id=item["inst_id"],
                inst_type=item["inst_type"],
                product_key=item["product_key"],
                direction=item["direction"],
                score=Decimal(item["score"]),
            )
        )
    return tuple(legs)
