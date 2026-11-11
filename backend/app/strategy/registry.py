"""策略注册表：组件、模板、策略三张表，import-time 装饰器登记，按名字取实现。

登记复用 `app.core` 的注册表原语：指标与策略族共用同一套「按 kind 取名字」的机制，
不另写目录扫描或动态导入。各自的模块加一行 `@register_*` 即完成登记，装配层只需要
`get_component` / `get_template` / `get_strategy`。

三张表分开而不是一张：组件是「单标的判断」、模板是「组合方式」、策略是「直接产出
目标组合的旧式实现」，同名不冲突也不互相顶替——合并成一张会让一次误登记悄悄覆盖
另一类实现。

登记名取自各实现自己声明的名字，一处声明、一处使用：装饰器不需要再重复写一遍。
"""

from __future__ import annotations

from typing import cast

from app.core import InvariantViolation, get, list_names, register
from app.strategy.params import resolve_params
from app.strategy.protocol import Component, Strategy, Template

__all__ = [
    "get_component",
    "get_strategy",
    "get_template",
    "list_components",
    "list_strategies",
    "list_templates",
    "register_component",
    "register_strategy",
    "register_template",
]

_COMPONENT = "component"
_TEMPLATE = "template"
_STRATEGY = "strategy"


def register_component(component: type[Component]) -> type[Component]:
    """登记一个组件类，返回类本身。

    登记前检查名字：空名字无法被模板引用，属于声明错误，应当在 import 时就炸掉。
    """

    name = getattr(component, "name", "")
    if not isinstance(name, str) or not name.strip():
        raise InvariantViolation("组件必须声明非空的 name")
    return cast("type[Component]", register(_COMPONENT, name)(component))


def register_template(template: type[Template]) -> type[Template]:
    """登记一个模板类，返回类本身。

    与策略一样先用默认值跑一遍参数 schema：默认值越界或类型不对属于声明错误，
    应当在 import 时就炸掉，而不是等用户第一次打开参数面板。
    """

    resolve_params(template.param_schema)
    return cast("type[Template]", register(_TEMPLATE, template.meta.name)(template))


def register_strategy(strategy: type[Strategy]) -> type[Strategy]:
    """登记一个策略类，返回类本身。

    登记前先用默认值跑一遍参数 schema：默认值越界或类型不对属于声明错误，应当在
    import 时就炸掉，而不是等用户第一次打开参数面板。
    """

    resolve_params(strategy.param_schema)
    return cast("type[Strategy]", register(_STRATEGY, strategy.meta.name)(strategy))


def get_component(name: str) -> type[Component]:
    """按登记名取组件类；未命中时抛 `ValidationError`。"""

    return cast("type[Component]", get(_COMPONENT, name))


def get_template(name: str) -> type[Template]:
    """按登记名取模板类；未命中时抛 `ValidationError`。"""

    return cast("type[Template]", get(_TEMPLATE, name))


def get_strategy(name: str) -> type[Strategy]:
    """按登记名取策略类；未命中时抛 `ValidationError`。"""

    return cast("type[Strategy]", get(_STRATEGY, name))


def list_components() -> list[str]:
    """已登记的组件名，按字典序。"""

    return list_names(_COMPONENT)


def list_templates() -> list[str]:
    """已登记的模板名，按字典序。

    旧式策略不在本表里：它们能产出目标组合，但不是可选的组合模板。
    """

    return list_names(_TEMPLATE)


def list_strategies() -> list[str]:
    """已登记的策略名，按字典序。"""

    return list_names(_STRATEGY)
