"""实现注册表原语。

indicators / strategy / provider 三处都要「按名字取实现」，共用同一份注册表，
避免各写一套发现机制。这里只有登记与查找：加载器、目录扫描、动态发现、沙箱都不
属于本层，等真的有第三方插件时再谈。

登记名是代码里写死的标识（如 `@register("indicator", "sma")`），不是用户输入的
自由文本；`get` 未命中说明调用方问了一个不存在的名字，按参数不合法处理。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from app.core.errors import InvariantViolation, ValidationError

__all__ = ["get", "list_names", "register"]

_T = TypeVar("_T")

# kind → name → 实现对象。按 kind 分桶，不同类别的同名实现互不干扰。
_REGISTRY: dict[str, dict[str, Any]] = {}


def register(kind: str, name: str) -> Callable[[_T], _T]:
    """登记装饰器：`@register("indicator", "sma")`，返回被装饰对象本身。

    同一个 kind 下重复登记同名实现属于装配错误，直接抛 `InvariantViolation`：
    被后者悄悄覆盖会让「注册了哪个」变成不可见的状态。
    """

    def _register(obj: _T) -> _T:
        bucket = _REGISTRY.setdefault(kind, {})
        if name in bucket:
            raise InvariantViolation(f"{kind} 实现重复登记:{name}")
        bucket[name] = obj
        return obj

    return _register


def get(kind: str, name: str) -> Any:
    """按名字取实现；未命中时抛 `ValidationError`，消息里列出该类已登记的名字。"""

    bucket = _REGISTRY.get(kind, {})
    if name not in bucket:
        available = ", ".join(sorted(bucket)) or "(空)"
        raise ValidationError(f"未登记的 {kind}:{name}; 已登记: {available}")
    return bucket[name]


def list_names(kind: str) -> list[str]:
    """已登记的实现名，按字典序；从未登记过的 kind 返回空列表。"""

    return sorted(_REGISTRY.get(kind, {}))
