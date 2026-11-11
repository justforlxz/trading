"""六个基础组件：可复用的单标的（或横截面）判断，彼此不知道对方存在。

组件只回答「现在这个标的偏多还是偏空、强度多少」，不回答「买多少」：配权、选腿
数与组合形态属于模板。这样同一个判断可以被不同模板以不同方式使用，指标换算法也
不会外溢到组合层。

分数口径统一在 `ComponentSignal`：产品键 → 有符号分数，恒在 `[-1, 1]`。原始量纲
（均线偏离比例、收益率、相关系数变化）各不相同，因此每个组件先用 `squash` 压到
同一区间；模板才能把几个组件的分数直接相加。

组件都是纯函数式的：`evaluate` 只读 `MarketView`，不取数、不写库、不看时钟，同一
份视图重复调用得到相同结果。数据不够判断的产品不出现在 `scores` 里，而不是补一个
中性分数。

横截面类组件（广度、相对强弱）按约定只吃「同一资产类别、同一周期、同一时点」的
一组产品，类别由装配层构造视图时分组，组件不猜产品属于哪一类。
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.core import Bar, ValidationError

__all__ = [
    "Breadth",
    "CorrelationShift",
    "MeanReversion",
    "Momentum",
    "RelativeStrength",
    "Trend",
    "check_window",
    "closes",
    "simple_return",
    "squash",
]

_ONE = Decimal(1)


def check_window(window: int) -> int:
    """窗口必须是正整数：0 或负数的窗口没有「最近多少根」的含义。"""

    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValidationError(f"组件的窗口必须是正整数, 实际 {window!r}")
    return window


def squash(raw: Decimal) -> Decimal:
    """把无量纲原始值压到 `(-1, 1)`：`raw / (1 + |raw|)`。

    选这个形状而不是 `tanh` 或截断：全仓算金额与比例都用 `Decimal`，`tanh` 只能走
    浮点；截断会让「涨 3%」与「涨 30%」并列第一。这个映射单调、零保持零、值域有界，
    且只用到加减乘除。
    """

    return raw / (_ONE + abs(raw))


def closes(bars: Sequence[Bar]) -> list[Decimal]:
    """K 线的收盘价序列；视图保证已按 `open_time` 升序。"""

    return [bar.close for bar in bars]


def simple_return(values: Sequence[Decimal], window: int) -> Decimal | None:
    """最近 `window` 根的单期收益率；样本不足或起点为 0 时给 `None`。"""

    check_window(window)
    if len(values) <= window:
        return None
    start = values[-window - 1]
    if start == 0:
        return None
    return values[-1] / start - _ONE


# 导入即登记六个组件。放在文件末尾：子模块要回头取本模块的 `squash` / `closes` 等
# 公共函数，只有先把它们定义好，这里的导入才不会拿到半初始化的模块。
from app.strategy.components.breadth import Breadth  # noqa: E402
from app.strategy.components.correlation_shift import CorrelationShift  # noqa: E402
from app.strategy.components.mean_reversion import MeanReversion  # noqa: E402
from app.strategy.components.momentum import Momentum  # noqa: E402
from app.strategy.components.relative_strength import RelativeStrength  # noqa: E402
from app.strategy.components.trend import Trend  # noqa: E402
