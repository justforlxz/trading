"""市场广度与共振：把一个类别下的一组标的压成两个数。

两者都是横截面统计，输入是「同一类别、同一周期、同一时点」的一组序列，因此
**不跨类别混算**：`SPOT` 与 `SWAP` 的交易时段不同，把两类放在同一个横截面里
统计出来的涨跌家数没有意义。类别由调用方分组，这里只吃一组同类别的序列。

两个函数都是纯函数：不读库、不看时钟、不插值。参与标的的口径只有一条——该
标的在窗口内至少有 2 根 K 线；不足 2 根（或一根都没有）时方向无从判断，不计入
参与标的，也不补一个「不变」出来。

- `advance_decline`：最后一根与上一根收盘价比，数上涨 / 下跌 / 不变的家数。
- `resonance_strength`：窗口首尾收盘价比，看这组标的同向的程度。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core import Bar, ValidationError

# 共振强度需要的最小参与标的数：样本太少的「共振」没有意义，宁可给 `None`。
MIN_RESONANCE_PARTICIPANTS = 5


@dataclass(frozen=True, slots=True)
class Breadth:
    """一组同类标的的涨跌家数。

    `ratio` 是上涨家数除以下跌家数；没有下跌标的时除以零不成立，如实给 `None`，
    不写成无穷大或一个很大的数。`participants` 是三项之和，等于窗口内至少有
    2 根 K 线的标的数。
    """

    advancers: int
    decliners: int
    unchanged: int
    ratio: float | None
    participants: int


@dataclass(frozen=True, slots=True)
class Resonance:
    """一组同类标的在窗口内的同向程度：恒在 `[0, 1]`。

    全部同向（全涨或全跌）为 `1`，涨跌各半为 `0`，不变与无方向的标的拉低强度。
    参与标的少于 `MIN_RESONANCE_PARTICIPANTS` 时 `strength` 为 `None`：样本不足
    时给出一个「强度」比留空更糟。
    """

    strength: float | None
    participants: int
    window: int


def _by_open_time(bars: Sequence[Bar]) -> list[Bar]:
    """按 `open_time` 升序排；取数顺序不可信，方向判断不能被入参顺序左右。"""

    return sorted(bars, key=lambda candle: candle.open_time)


def advance_decline(bars_by_symbol: Mapping[str, Sequence[Bar]]) -> Breadth:
    """数最后一根 K 线相对上一根的涨跌家数。

    只比较相邻两根的收盘价，不看更早的历史：这是「此刻有多少标的在涨」的问题，
    不是「谁涨得最多」。
    """

    advancers = decliners = unchanged = 0
    for bars in bars_by_symbol.values():
        ordered = _by_open_time(bars)
        if len(ordered) < 2:
            continue
        change = ordered[-1].close - ordered[-2].close
        if change > 0:
            advancers += 1
        elif change < 0:
            decliners += 1
        else:
            unchanged += 1

    return Breadth(
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        ratio=None if decliners == 0 else advancers / decliners,
        participants=advancers + decliners + unchanged,
    )


def resonance_strength(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    window: int,
) -> Resonance:
    """窗口首尾收盘价定方向，`|上涨家数 - 下跌家数| / 参与标的数` 即同向程度。

    每个标的只看最近 `window + 1` 根：跨过窗口的部分不参与判断，因此「窗口」是
    真的窗口，不是随便一段历史。K 线不足 `window + 1` 根但至少有 2 根时，用它能
    提供的这段，不为了凑满窗口去读更早的数据。
    """

    if window < 1:
        raise ValidationError(f"共振窗口必须是正整数:{window}")

    rising = falling = flat = 0
    for bars in bars_by_symbol.values():
        ordered = _by_open_time(bars)[-(window + 1) :]
        if len(ordered) < 2:
            continue
        change = ordered[-1].close - ordered[0].close
        if change > 0:
            rising += 1
        elif change < 0:
            falling += 1
        else:
            flat += 1

    participants = rising + falling + flat
    if participants < MIN_RESONANCE_PARTICIPANTS:
        return Resonance(strength=None, participants=participants, window=window)
    return Resonance(
        strength=abs(rising - falling) / participants,
        participants=participants,
        window=window,
    )
