"""装配层的外部行情 Provider 选择：设置里的名字 → 适配器实例。

三个路由都要做同一件事，放在这里避免各自实现后行为漂移。业务域不读设置表，也不
依赖 HTTP 契约；这层只做「读设置、查登记表」两件事。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import ValidationError
from app.market import MarketOverviewProvider, get_provider
from app.settings import load_settings

__all__ = ["ProviderSelection", "configured_provider_name", "select_provider"]


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """一次选择的结果：名字、适配器，以及名字已配置但未登记时的错误文本。"""

    name: str | None
    provider: MarketOverviewProvider | None
    error: str | None


def select_provider() -> ProviderSelection:
    """读取设置里的 Provider 并构造适配器。

    没有配置时三项都为 `None`；名字已配置但未登记时给出错误文本而不抛异常，由调用
    方决定是返回陈旧状态还是拒绝请求。读取设置本身抛错时不吞掉，交给调用方处理。
    """

    name = configured_provider_name()
    if name is None:
        return ProviderSelection(name=None, provider=None, error=None)
    try:
        return ProviderSelection(name=name, provider=get_provider(name), error=None)
    except ValidationError as exc:
        return ProviderSelection(name=name, provider=None, error=str(exc))


def configured_provider_name() -> str | None:
    """只读设置里的 Provider 名，不构造适配器。

    健康接口只关心「配置了哪个名字」，不需要实例；构造失败也不该让它变成「未配置」。
    """

    raw = load_settings().data_sources.get("provider")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()
