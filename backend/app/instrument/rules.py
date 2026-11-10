"""按类别（SPOT / SWAP）的交易规则集合。

类别差异只在这一处定义：一类一张表，其余模块查表取值，不写 `inst_type == "…"`
分支。新增类别 = 注册一张新表，已有类别的取值一格都不动。

规则是纯静态数据：不含行情、不读数据库、不看账户，同一个 `inst_type` 永远得到
同一张表。随标的或行情变化的量（例如永续真正可用的杠杆上限）不在本表里，由本表
声明「去上游取」，取值时读标的自身字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core import ValidationError
from app.instrument.model import SPOT, SWAP

__all__ = ["SPOT_RULES", "SWAP_RULES", "TradingRules", "register_rules", "trading_rules"]


@dataclass(frozen=True, slots=True)
class TradingRules:
    """一个类别的静态交易规则。

    `max_leverage` 为 `None` 有两层含义，靠 `has_margin` 区分：现货没有杠杆
    （`has_margin=False`），永续不设本地上限、用标的自身的 `maxLever`
    （`has_margin=True`）。

    `state_kinds` 是该类别可能出现的上游状态集合：两类都含 `preopen`。仓库内已有
    事实是现货列表同样会出现 `preopen`——`parse_instruments` 专门放过单条预上线记录
    以免拖垮整批现货列表，`_data_start` 也不分类别地判 `preopen`；没有证据支持两类
    不同，因此不做区分。
    """

    tick_size_required: bool
    min_order_size_required: bool
    max_leverage: Decimal | None
    has_margin: bool
    has_funding: bool
    funding_interval_hours: int | None
    session_kind: str
    state_kinds: frozenset[str]
    has_position_endpoint: bool
    qty_unit: str


SPOT_RULES = TradingRules(
    tick_size_required=True,
    min_order_size_required=True,
    max_leverage=None,
    has_margin=False,
    has_funding=False,
    funding_interval_hours=None,
    session_kind="crypto_24_7",
    state_kinds=frozenset({"live", "suspend", "preopen"}),
    has_position_endpoint=False,
    qty_unit="base",
)

SWAP_RULES = TradingRules(
    tick_size_required=True,
    min_order_size_required=True,
    max_leverage=None,
    has_margin=True,
    has_funding=True,
    funding_interval_hours=8,
    session_kind="equity",
    state_kinds=frozenset({"live", "suspend", "preopen"}),
    has_position_endpoint=True,
    qty_unit="contract",
)

#: 类别 → 规则。新增类别只在这里加一行，不动已有条目。
_RULES: dict[str, TradingRules] = {SPOT: SPOT_RULES, SWAP: SWAP_RULES}


def trading_rules(inst_type: str) -> TradingRules:
    """取该类别的规则；未注册的类别直接报错，不返回默认值。"""

    name = _normalize(inst_type)
    rules = _RULES.get(name)
    if rules is None:
        raise ValidationError(f"标的类别 {name!r} 没有注册交易规则")
    return rules


def register_rules(inst_type: str, rules: TradingRules) -> None:
    """注册一个类别的规则；同名类别覆盖旧的表。

    这是「新增类别」的唯一入口：注册完即可被 `trading_rules` 查到，已有类别的
    返回值不受影响。
    """

    _RULES[_normalize(inst_type)] = rules


def _normalize(inst_type: str) -> str:
    name = inst_type.strip().upper()
    if not name:
        raise ValidationError("标的类别不能为空")
    return name
