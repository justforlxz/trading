"""只读行情视图：策略能看到的全部输入。

这一层不碰 IO：K 线、关系矩阵在构造视图之前由装配层取好，策略只在这份快照上读。
因此策略拿不到会话、连接或交易客户端，同一个视图上重复计算得到相同结果。

视图按「产品键 → 周期 → K 线」组织，一次可以取多个标的：需要多个标的的策略不必
逐个调用取数入口，也就不会出现「取到一半行情变了」这类半新半旧的输入。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from app.core import Bar, ValidationError
from app.indicators import ParamValue, Series, compute
from app.market import Matrix
from app.shared import normalize_bar

__all__ = ["MarketView"]


def _canonical_bar(bar: str) -> str:
    """视图的周期键必须是规范写法；上游别名只在交易所适配层出现。"""

    try:
        canonical = normalize_bar(bar)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    if canonical != bar:
        raise ValidationError(f"行情视图的周期必须是规范写法:{bar!r}, 应为 {canonical!r}")
    return canonical


def _readonly_candles(
    candles: Mapping[str, Mapping[str, Sequence[Bar]]],
) -> Mapping[str, Mapping[str, tuple[Bar, ...]]]:
    """把入参冻结成只读结构：外层与内层都是只读映射，序列换成按时间升序的元组。"""

    frozen: dict[str, Mapping[str, tuple[Bar, ...]]] = {}
    for product_key, series in candles.items():
        if not isinstance(product_key, str) or not product_key.strip():
            raise ValidationError("行情视图的 product_key 不能为空")
        by_bar: dict[str, tuple[Bar, ...]] = {}
        for bar, bars in series.items():
            canonical = _canonical_bar(bar)
            ordered = tuple(sorted(bars, key=lambda item: item.open_time))
            for item in ordered:
                if item.timeframe.value != canonical:
                    raise ValidationError(
                        f"行情视图 {product_key} 的 {canonical} 下混入了 "
                        f"{item.timeframe.value} 的 K 线"
                    )
            by_bar[canonical] = ordered
        frozen[product_key] = MappingProxyType(by_bar)
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class MarketView:
    """策略读的只读快照：时点、各产品的 K 线、关系矩阵。

    `as_of` 是这份快照的时点，关系矩阵必须按同一时点算出：两者不一致说明视图由不同
    时刻的数据拼成，直接拒绝，而不是让策略读到混合时点的输入。
    """

    as_of: datetime
    candles: Mapping[str, Mapping[str, Sequence[Bar]]]
    matrix: Matrix

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValidationError("行情视图的 as_of 必须带时区")
        if self.matrix.as_of != self.as_of:
            raise ValidationError(
                f"行情视图的 as_of 与关系矩阵不一致:{self.as_of.isoformat()} != "
                f"{self.matrix.as_of.isoformat()}"
            )
        object.__setattr__(self, "candles", _readonly_candles(self.candles))

    @property
    def product_keys(self) -> tuple[str, ...]:
        """视图覆盖的产品键，按构造顺序。"""

        return tuple(self.candles)

    def bars(self, product_keys: Iterable[str], bar: str) -> dict[str, tuple[Bar, ...]]:
        """一次取多个标的、同一周期的 K 线；缺任何一个都整体报错。

        返回的序列按 `open_time` 升序，指标与滚动计算可以直接使用。缺失不静默跳过：
        少一个标的会让组合整体失真，调用方应当先把行情取齐再构造视图。
        """

        canonical = _canonical_bar(bar)
        ordered = list(dict.fromkeys(product_keys))
        missing = [
            key for key in ordered if key not in self.candles or canonical not in self.candles[key]
        ]
        if missing:
            raise ValidationError(f"行情视图缺少 {canonical} K 线的产品:{', '.join(missing)}")
        return {key: self.candles[key][canonical] for key in ordered}

    def indicators(
        self,
        product_keys: Iterable[str],
        name: str,
        bar: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> dict[str, Series]:
        """一次算多个标的的同一个指标；指标计算是纯函数，不改视图。"""

        return {
            key: compute(name, bars, params) for key, bars in self.bars(product_keys, bar).items()
        }
