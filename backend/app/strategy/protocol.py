"""策略协议：一类策略必须提供什么，才能被注册表与引擎按同一种方式调用。

协议只描述策略的对外形状：声明（`meta`）、可调参数（`param_schema`）、对行情的要求
（`requires`）与一次计算（`evaluate`）。计算只读 `MarketView`，只产出 `TargetPortfolio`，
因此策略碰不到交易所、账户与会话，也不会产出单标的的动作序列。

具体策略（组件与模板）由后续节点实现，本模块只固定接口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core import ValidationError
from app.indicators import Param
from app.shared import normalize_bar
from app.strategy.target import TargetPortfolio
from app.strategy.view import MarketView

__all__ = ["Requirements", "Strategy", "StrategyMeta"]


@dataclass(frozen=True, slots=True)
class StrategyMeta:
    """策略的对外声明：登记名、展示标题、一句话说明。

    登记名在注册表里唯一，是代码里写死的标识（如 `trend_following`），不是用户输入
    的自由文本；标题与说明供界面展示与人工审核。
    """

    name: str
    title: str
    summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("策略的 name 不能为空")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValidationError("策略的 title 不能为空")


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
