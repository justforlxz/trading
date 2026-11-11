"""机会发现：把一组标的的行情与相关关系压成「值得做、往哪个方向做」的候选。

两种模式共用同一套评分与筛选：

- 目标驱动（`target`）：给定锚点，只保留与它相关、且自身有方向的邻居；锚点自身
  没有方向时它不会因为「它是锚点」被塞进组合——锚点只是分析起点，不要求成为候选
  的一员。
- 市场驱动（`market`）：不给锚点，按类别各自看整类标的的同向程度与涨跌家数，
  腿是该方向上自身有方向的标的。两类标的的交易时段不同，因此分开统计，不放进
  同一个横截面。

方向的唯一来源是窗口内的首尾收盘价，涨跌家数与同向程度直接复用
`app.market` 的纯函数（T2.5 交付的口径，这里不另算一套）。筛选的门槛只有两条：
最小趋势幅度与最小相关系数绝对值。

全部是纯函数：不读库、不看时钟，同一份输入两次调用得到同一份输出。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core import Bar
from app.market import advance_decline, resonance_strength

__all__ = [
    "LEG_LIMIT",
    "LONG",
    "MIN_ABS_CORRELATION",
    "MIN_RESONANCE",
    "MIN_TREND",
    "MODE_MARKET",
    "MODE_TARGET",
    "SHORT",
    "WINDOW_BARS",
    "Candidate",
    "Leg",
    "Observation",
    "leg_of",
    "market_candidates",
    "target_candidate",
    "trend",
]

MODE_TARGET = "target"
MODE_MARKET = "market"

# 腿的方向取值，与契约的 `PositionSide` 同值。
LONG = "long"
SHORT = "short"

# 评分窗口：每个标的看最近 `WINDOW_BARS + 1` 根 K 线。与 T2.5 的共振窗口同口径，
# 窗口首尾收盘价定方向。
WINDOW_BARS = 20

# 有信号的最小趋势幅度（窗口首尾涨跌幅的绝对值）：更小的波动不构成一个方向。
MIN_TREND = 0.01

# 目标驱动里「邻居」的最小相关系数绝对值，与关系网络的默认阈值同口径。
MIN_ABS_CORRELATION = 0.5

# 市场驱动要求的最小同向程度：涨跌各半的市场不构成共振。
MIN_RESONANCE = 0.2

# 一条机会最多几条腿：候选是给人看的组合起点，不是把整个类别抄一遍。
LEG_LIMIT = 5

# 分数与契约的 `DecimalString` 对齐：6 位小数足够区分强弱，且同一份输入逐字相同。
_SCORE_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Observation:
    """一个标的在一个窗口上的可算依据：身份、行情来源与按 `open_time` 升序的 K 线。

    `source` 随样本一起带着，是因为不同来源的 K 线不能用同一个时间轴对齐
    （代理日线开在美东 09:30、OKX 日线开在 16:00 UTC），相关系数只在同一来源的
    两个标的之间计算。
    """

    product_key: str
    inst_id: str
    inst_type: str
    source: str
    bars: tuple[Bar, ...]


@dataclass(frozen=True, slots=True)
class Leg:
    """候选腿：某个标的的方向与自身强度；目标权重由 T3.5 的组合生成给出。"""

    inst_id: str
    inst_type: str
    product_key: str
    direction: str
    score: Decimal


@dataclass(frozen=True, slots=True)
class Candidate:
    """一条检测出来的机会：模式、锚点、综合分数、腿与判定依据。

    `evidence` 是判定依据的普通字典（相关系数、广度、共振等），由调用方原样序列化
    成 JSON 文本落库；本模块不做序列化，也不解释这些数字。
    """

    mode: str
    anchor_product_key: str | None
    as_of: datetime
    score: Decimal
    legs: tuple[Leg, ...]
    evidence: Mapping[str, object]


def trend(bars: Sequence[Bar]) -> float:
    """窗口首尾收盘价的相对变化率；不足两根时给 0（没有方向，也不补一个出来）。

    取数顺序不可信：先按 `open_time` 排序，方向判断不能被入参顺序左右。
    """

    ordered = sorted(bars, key=lambda candle: candle.open_time)
    if len(ordered) < 2:
        return 0.0
    first = float(ordered[0].close)
    return (float(ordered[-1].close) - first) / first


def leg_of(observation: Observation, *, min_trend: float = MIN_TREND) -> Leg | None:
    """一个标的自身的候选腿；趋势幅度不到门槛时它没有方向，返回 `None`。"""

    change = trend(observation.bars)
    if abs(change) < min_trend:
        return None
    return Leg(
        inst_id=observation.inst_id,
        inst_type=observation.inst_type,
        product_key=observation.product_key,
        direction=LONG if change > 0 else SHORT,
        score=_score(abs(change)),
    )


def target_candidate(
    anchor: Observation,
    peers: Sequence[Observation],
    correlations: Mapping[str, float | None],
    *,
    as_of: datetime,
    min_abs_correlation: float = MIN_ABS_CORRELATION,
    min_trend: float = MIN_TREND,
    limit: int = LEG_LIMIT,
) -> Candidate | None:
    """目标驱动的唯一一条机会：锚点 + 与它相关且自身有方向的邻居。

    `correlations` 以产品键为键，值是它与锚点的相关系数；缺失或达不到门槛的邻居
    不进候选，系数未定义（样本不足）的同样不进。锚点自身有方向时也作为一条腿进来，
    没有方向时它就不在腿里——两种情形都不特殊处理，方向由 `leg_of` 一处判定。
    """

    legs: list[Leg] = []
    neighbour_correlations: list[float] = []
    for peer in peers:
        if peer.product_key == anchor.product_key:
            continue
        coefficient = correlations.get(peer.product_key)
        if coefficient is None or abs(coefficient) < min_abs_correlation:
            continue
        leg = leg_of(peer, min_trend=min_trend)
        if leg is None:
            continue
        legs.append(leg)
        neighbour_correlations.append(abs(coefficient))

    anchor_leg = leg_of(anchor, min_trend=min_trend)
    if anchor_leg is not None:
        legs.append(anchor_leg)

    selected = _selected(legs, limit)
    if not selected:
        return None
    return Candidate(
        mode=MODE_TARGET,
        anchor_product_key=anchor.product_key,
        as_of=as_of,
        score=_mean_score(selected),
        legs=selected,
        evidence={
            "anchor_product_key": anchor.product_key,
            "inst_type": anchor.inst_type,
            "min_abs_correlation": min_abs_correlation,
            "correlation": _mean_correlation(neighbour_correlations),
            "neighbours": len(neighbour_correlations),
        },
    )


def market_candidates(
    samples: Mapping[str, Sequence[Observation]],
    *,
    as_of: datetime,
    window: int = WINDOW_BARS,
    min_resonance: float = MIN_RESONANCE,
    min_trend: float = MIN_TREND,
    limit: int = LEG_LIMIT,
) -> tuple[Candidate, ...]:
    """市场驱动：逐个类别看整类标的的同向程度，一个类别至多一条机会。

    `samples` 的键是类别（`SPOT` / `SWAP`），值是该类别自己的标的样本：两类标的的
    交易时段不同，混进同一个横截面统计出来的涨跌家数没有意义。类别的方向由涨跌
    家数决定（上涨多于下跌为多头，反之为空头），同向程度不到门槛、或者涨跌家数
    相等的类别不产出机会。腿只取与类别方向一致的标的。
    """

    candidates: list[Candidate] = []
    for inst_type in sorted(samples):
        group = samples[inst_type]
        if not group:
            continue
        bars_by_product = {obs.product_key: obs.bars for obs in group}
        breadth = advance_decline(bars_by_product)
        resonance = resonance_strength(bars_by_product, window)
        if breadth.advancers == breadth.decliners:
            continue
        if resonance.strength is None or resonance.strength < min_resonance:
            continue

        direction = LONG if breadth.advancers > breadth.decliners else SHORT
        legs = [
            leg
            for obs in group
            if (leg := leg_of(obs, min_trend=min_trend)) is not None and leg.direction == direction
        ]
        selected = _selected(legs, limit)
        if not selected:
            continue
        candidates.append(
            Candidate(
                mode=MODE_MARKET,
                anchor_product_key=None,
                as_of=as_of,
                score=_mean_score(selected),
                legs=selected,
                evidence={
                    "inst_type": inst_type,
                    "direction": direction,
                    "resonance": None if resonance.strength is None else _round(resonance.strength),
                    "breadth": {
                        "advancers": breadth.advancers,
                        "decliners": breadth.decliners,
                        "unchanged": breadth.unchanged,
                        "participants": breadth.participants,
                    },
                    "window": window,
                },
            )
        )
    return tuple(candidates)


def _selected(legs: Sequence[Leg], limit: int) -> tuple[Leg, ...]:
    """按分数从大到小、同分按产品键取前 `limit` 条：腿的顺序也是结果的一部分。"""

    ordered = sorted(legs, key=lambda leg: (-leg.score, leg.product_key))
    return tuple(ordered[:limit])


def _mean_score(legs: Sequence[Leg]) -> Decimal:
    """机会的综合分数 = 各腿自身强度的平均，与腿的分数同一精度。"""

    total = sum((leg.score for leg in legs), Decimal(0))
    return (total / len(legs)).quantize(_SCORE_PLACES)


def _mean_correlation(values: Sequence[float]) -> float | None:
    """邻居相关系数的平均值；一个邻居都没有时如实给 `None`，不填 0。"""

    if not values:
        return None
    return _round(sum(values) / len(values))


def _score(value: float) -> Decimal:
    """浮点强度 → 定点分数：落库与出接口都是同一份十进制。"""

    return Decimal(str(value)).quantize(_SCORE_PLACES)


def _round(value: float) -> float:
    """判定依据里的浮点同样按分数的精度收敛，同一份输入两次输出逐字相同。"""

    return float(Decimal(str(value)).quantize(_SCORE_PLACES))
