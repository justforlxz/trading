"""策略协议：组件、模板与策略各自必须提供什么，才能被注册表按同一种方式调用。

协议只描述对外形状，不描述实现：

- `Component`：单标的（或横截面）判断，只读 `MarketView`，只产出 `ComponentSignal`；
- `Template`：把若干组件组合成目标组合，只读 `MarketView`，只产出 `TargetPortfolio`；
- `Strategy`：目标组合的直接生产者，形状与模板相同，是旧策略降级后的用法。

三者都只接收视图一个参数，因此碰不到交易所、账户与会话，也不会产出单标的的动作
序列；同一个视图上重复调用必须得到相同结果。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol

from app.core import ValidationError
from app.indicators import Param
from app.shared import normalize_bar
from app.strategy.target import TargetPortfolio
from app.strategy.view import MarketView

__all__ = [
    "Component",
    "ComponentSignal",
    "Requirements",
    "Strategy",
    "StrategyMeta",
    "Template",
]


@dataclass(frozen=True, slots=True)
class StrategyMeta:
    """策略的对外声明：登记名、展示标题、版本、一句话说明。

    登记名在注册表里唯一，是代码里写死的标识（如 `trend_following`），不是用户输入
    的自由文本；标题与说明供界面展示与人工审核。

    版本是复现的依据：策略实例创建时把当时的版本记下来，之后模板升级不影响历史实例
    报出的版本。改动了组合逻辑就必须手工递增版本，注册表不猜「什么时候算改」。
    """

    name: str
    title: str
    version: str = "1.0.0"
    summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("策略的 name 不能为空")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValidationError("策略的 title 不能为空")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValidationError(f"策略 {self.name} 的 version 不能为空")


@dataclass(frozen=True, slots=True)
class Requirements:
    """策略对行情的要求：用哪个周期、至少需要多少根已收盘 K 线。

    标的范围由视图覆盖的产品决定，不在这里重复声明：同一份视图可以喂给参数不同的
    多个策略实例，产品清单由装配层统一给出。
    """

    bar: str
    lookback: int

    def __post_init__(self) -> None:
        try:
            canonical = normalize_bar(self.bar)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        if canonical != self.bar:
            raise ValidationError(f"策略要求的 bar 必须是规范写法:{self.bar!r}, 应为 {canonical!r}")
        if self.lookback < 1:
            raise ValidationError(f"策略要求的 lookback 必须是正整数, 实际 {self.lookback}")


class Strategy(Protocol):
    """一类策略的接口。

    `evaluate` 只接收视图一个参数：策略不能自己去取数、也不能持有会话。同一份视图上
    重复调用必须得到相同结果，回测与实盘才能对得上。
    """

    meta: StrategyMeta
    param_schema: tuple[Param, ...]
    requires: Requirements

    def evaluate(self, view: MarketView) -> TargetPortfolio: ...


@dataclass(frozen=True, slots=True)
class ComponentSignal:
    """一个组件在一份视图上的读数：产品键 → 有符号分数，恒在 `[-1, 1]`。

    分数的符号表示方向，绝对值表示强度：正数看多、负数看空。符号由各组件自己的语义
    决定——趋势看价格站在均线的哪一侧，相关性变化看联动性在增强还是减弱；没有方向
    判断的组件不硬造一个方向出来。

    分数是无量纲的：不同组件的原始量纲（收益率、偏离比例、相关系数差）先各自归一
    到同一区间，模板才能按同一把尺子相加。没有读数的产品不出现在 `scores` 里——
    补一个 0 会被后续当成「中性判断」，而中性判断与「判断不出来」不是一回事。
    """

    name: str
    as_of: datetime
    scores: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("组件信号缺少组件名")
        if self.as_of.tzinfo is None:
            raise ValidationError("组件信号的 as_of 必须带时区")

        frozen: dict[str, Decimal] = {}
        for product_key, score in self.scores.items():
            if not isinstance(product_key, str) or not product_key.strip():
                raise ValidationError("组件信号的 product_key 不能为空")
            if not isinstance(score, Decimal):
                raise ValidationError(f"组件信号的分数必须是 Decimal, 实际 {type(score).__name__}")
            if not score.is_finite() or not -1 <= score <= 1:
                raise ValidationError(f"组件 {self.name} 对 {product_key} 的分数越界:{score}")
            frozen[product_key] = score

        object.__setattr__(self, "scores", MappingProxyType(frozen))


class Component(Protocol):
    """一个基础组件的接口：只读视图，只产出分数。

    `name` 是登记名（如 `trend`），在组件注册表里唯一，也是模板拼装时引用的名字。
    组件的参数在构造时给定（周期、窗口），因此 `evaluate` 只接收视图一个参数。
    """

    name: str

    def evaluate(self, view: MarketView) -> ComponentSignal: ...


class Template(Protocol):
    """一类组合模板的接口：把若干组件拼成目标组合。

    `build` 与 `evaluate` 一样只接收视图；模板自己决定用哪些组件、如何配权，因此
    组件换算法不会外溢到调用方。
    """

    meta: StrategyMeta
    param_schema: tuple[Param, ...]

    def build(self, view: MarketView) -> TargetPortfolio: ...
