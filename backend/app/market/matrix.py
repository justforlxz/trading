"""相关矩阵：一组标的在同一周期、同一来源、同一窗口上的两两相关系数。

纯计算与取数分开：`build_matrix` 只吃已经取好的 `(open_time, 值)` 序列，
`correlation_matrix` 负责按标的读出 K 线再交给它。缺样本的格子是 `None`——不插值、
不跨来源拼接，也不用相邻时刻顶替。

矩阵对称：`matrix[a][b] == matrix[b][a]`，对角线是标的与自己的相关（非恒定序列为
`1.0`，样本不足或方差为 0 时为 `None`）。交叉格与对角线走同一条「按 `open_time`
去重、取最近 `window` 个对齐样本」的路径，样本数只有一种口径。

来源是行情的一部分：同一标的混存多种来源的 K 线时，时间轴无法用同一个网格对齐
（代理日线开在美东 09:30、OKX 日线开在 16:00 UTC），而且同一 `open_time` 会有两行
互相顶替。因此 `correlation_matrix` 要求来源明确：调用方指定，或库里该标的该周期
只有一种来源；出现多种来源又没指定时直接报错，不静默挑一个。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import ValidationError
from app.market.correlation import pearson
from app.market.rolling import Point, index_series
from app.market.sync import candle_sources, load_candles, normalize_bar_or_raise


@dataclass(frozen=True, slots=True)
class Matrix:
    """一张相关性矩阵。

    `symbols` 是矩阵的标识序列（顺序即行列顺序）；`coefficients[a][b]` 是第 a 行第
    b 列的系数，因此 `matrix[a][b]` 直接可用。`samples` 以 `(a, b)` 为键记录该格子
    实际用到的样本条数，两个方向都记同一个数。

    标识是调用方给的（现算时是交易所标识 `symbol`，回看快照时是产品键
    `product_key`）：本类型只负责「一组标识 + 两两系数」，不替调用方判断标识语义。
    """

    symbols: tuple[str, ...]
    bar: str
    window: int
    as_of: datetime
    coefficients: Mapping[str, Mapping[str, float | None]]
    samples: Mapping[tuple[str, str], int]

    def __getitem__(self, symbol: str) -> Mapping[str, float | None]:
        """按行取：`matrix[a][b]` 与 `matrix[b][a]` 恒等。"""

        return self.coefficients[symbol]

    def sample_size(self, symbol_a: str, symbol_b: str) -> int:
        """某个格子实际用到的样本条数（两个方向一致）。"""

        return self.samples[(symbol_a, symbol_b)]


def _validate(symbols: Sequence[str], window: int, as_of: datetime) -> tuple[str, ...]:
    """参数校验前置：非法输入在取数之前就报错，不白读一遍历史。"""

    ordered = tuple(symbols)
    if not ordered:
        raise ValidationError("相关矩阵至少需要一个标的")
    if len(set(ordered)) != len(ordered):
        raise ValidationError(f"相关矩阵的标的不能重复:{ordered}")
    if window < 1:
        raise ValidationError(f"相关矩阵的窗口必须是正整数:{window}")
    if as_of.tzinfo is None:
        raise ValidationError("相关矩阵的 as_of 必须带时区")
    return ordered


def _tail(
    left: Mapping[datetime, float],
    right: Mapping[datetime, float],
    timeline: Sequence[datetime],
    window: int,
) -> list[tuple[float, float]]:
    """从时间轴末尾往前取最近 `window` 个两侧都有的取值。

    交叉格与对角线都走这里：对角线就是标的与自己配对，因此「同刻只取一个值」这条
    规则只有一处实现，样本数不会因为走了另一条路径而对不上。
    """

    pairs: list[tuple[float, float]] = []
    for moment in reversed(timeline):
        left_value = left.get(moment)
        if left_value is None:
            continue
        right_value = right.get(moment)
        if right_value is None:
            continue
        pairs.append((left_value, right_value))
        if len(pairs) == window:
            break
    pairs.reverse()
    return pairs


def build_matrix(
    symbols: Sequence[str],
    series: Mapping[str, Sequence[Point]],
    *,
    bar: str,
    window: int,
    as_of: datetime,
) -> Matrix:
    """把已经取好的序列拼成矩阵；不读库，也不判断标的身份或来源。

    每个格子用「两条序列按 `open_time` 取交集后、`as_of` 之前最近 `window` 个样本」
    算 Pearson 系数。交集不足 3 条（`MIN_SAMPLES`）时系数为 `None`，`samples` 仍如实
    写实际条数。每个标的的时间戳索引只建一次、时间轴只排序一次，标的对之间复用。
    """

    ordered = _validate(symbols, window, as_of)
    indexed = {
        symbol: {
            moment: value
            for moment, value in index_series(series[symbol], label=symbol).items()
            if moment <= as_of
        }
        for symbol in ordered
    }
    timeline = sorted({moment for index in indexed.values() for moment in index})

    coefficients: dict[str, dict[str, float | None]] = {symbol: {} for symbol in ordered}
    samples: dict[tuple[str, str], int] = {}
    for position, symbol_a in enumerate(ordered):
        for symbol_b in ordered[position:]:
            block = _tail(indexed[symbol_a], indexed[symbol_b], timeline, window)
            coefficient = pearson([left for left, _ in block], [right for _, right in block])
            coefficients[symbol_a][symbol_b] = coefficient
            coefficients[symbol_b][symbol_a] = coefficient
            samples[(symbol_a, symbol_b)] = len(block)
            samples[(symbol_b, symbol_a)] = len(block)

    return Matrix(
        symbols=ordered,
        bar=bar,
        window=window,
        as_of=as_of,
        coefficients=coefficients,
        samples=samples,
    )


def _resolve_source(
    symbol: str,
    bar: str,
    sources: Mapping[str, set[str]],
    requested: str | None,
) -> str | None:
    """该标的读哪个来源的 K 线：调用方指定优先，否则要求库里只有一种来源。"""

    if requested is not None:
        return requested
    available = sources.get(symbol, set())
    if len(available) > 1:
        raise ValidationError(
            f"标的 {symbol} 的 {bar} K 线有多种来源 {sorted(available)}, 请显式指定 source"
        )
    return next(iter(available), None)


def correlation_matrix(
    symbols: Sequence[str],
    bar: str,
    window: int,
    as_of: datetime,
    *,
    source: str | None = None,
) -> Matrix:
    """按交易所标识读出同周期、同来源的 K 线，拼出 `as_of` 时点的相关矩阵。

    取数只读库：每个标的分开读，缺多少就少多少，两两按 `open_time` 取交集后算系数。
    `as_of` 本身算在窗口内（`open_time` 精确到秒、读取区间是半开窗口，因此上界加一秒）。

    `source` 与库里实际落过的来源同值（`okx_spot` / `okx_swap` / 美股代理源标识）。
    不传时按标的逐个解析：库里只有一种来源就用它，出现多种来源直接报错——不同来源
    的 K 线不能进同一条序列，也不能靠数据库返回顺序挑一行。

    下界不做「往前推 `window` 根」的预筛：交集会因为某一侧缺样本而变短，预筛会静默
    改变结果，所以按真实历史读到 `as_of` 为止，标的范围由调用方控制。
    """

    ordered = _validate(symbols, window, as_of)
    canonical = normalize_bar_or_raise(bar)
    sources = candle_sources(ordered, canonical)
    end = as_of + timedelta(seconds=1)
    series = {
        symbol: [
            (candle.open_time, float(candle.close))
            for candle in load_candles(
                symbol,
                canonical,
                end=end,
                source=_resolve_source(symbol, canonical, sources, source),
            )
        ]
        for symbol in ordered
    }
    return build_matrix(ordered, series, bar=canonical, window=window, as_of=as_of)
