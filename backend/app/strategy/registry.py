"""策略注册表：import-time 装饰器登记，按名字取实现。

登记复用 `app.core` 的注册表原语：指标与策略共用同一套「按 kind 取名字」的机制，
不另写目录扫描或动态导入。策略类在自己的模块里加一行 `@register_strategy` 即完成
登记，装配层只需要 `get_strategy(name)`。

登记名取自 `meta.name`，一处声明、一处使用：装饰器不需要再重复写一遍名字。
"""

from __future__ import annotations

from typing import cast

from app.core import get, list_names, register
from app.strategy.params import resolve_params
from app.strategy.protocol import Strategy

__all__ = ["get_strategy", "list_strategies", "register_strategy"]

_KIND = "strategy"


def register_strategy(strategy: type[Strategy]) -> type[Strategy]:
    """登记一个策略类，返回类本身。

    登记前先用默认值跑一遍参数 schema：默认值越界或类型不对属于声明错误，应当在
    import 时就炸掉，而不是等用户第一次打开参数面板。
    """

    resolve_params(strategy.param_schema)
    return cast("type[Strategy]", register(_KIND, strategy.meta.name)(strategy))


def get_strategy(name: str) -> type[Strategy]:
    """按登记名取策略类；未命中时抛 `ValidationError`。"""

    return cast("type[Strategy]", get(_KIND, name))


def list_strategies() -> list[str]:
    """已登记的策略名，按字典序。"""

    return list_names(_KIND)
