"""第三方行情源的取数与解析：`RawBar` 是「上游给了什么」，还不算 K 线。

上游地址不在实现里：调用方从设置里读出地址模板后作为 `options` 传入，所以「换一个
源」只要改 `settings.data_sources.equity.provider`，抓取代码不动。

两个实现：

- `yahoo`：Yahoo chart API，分钟级。**免费源是延迟行情**（15 分钟级），`delayed`
  如实标 `True`，不当实时；要真实时只能接付费源。
- `stooq`：Stooq 的 CSV 下载，只有日线。免费、无需 key，作为备用。

`bar` / `delayed` 由实现自己声明：Yahoo 只给分钟级、Stooq 只给日线，切换 provider
就换了落库周期，这一点会在 `candles.bar` 上直接可见，不靠调用方猜。

**本层不认识「交易时段」**：把上游时刻对齐成该市场的开盘定界、算出 `market_session`
都是行情域的事（`app/equity/providers.py`）。这一层只把上游的字段搬成 `RawBar`，
因此它只依赖 `app.core` 的值对象与 `app.shared` 的周期表，不碰行情域规则。

上游异常或内容无法理解时抛 `UpstreamError`，由服务层记失败并降级为库里已有的值——
不返回空列表冒充「这段时间没有行情」，两者对用户是不同的事实。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.config import get_settings
from app.core import get, list_names, register
from app.exchange.providers.stooq import StooqSource
from app.exchange.providers.yahoo import YahooSource

__all__ = [
    "EQUITY_SOURCE_KIND",
    "build_source",
    "source_bar",
    "source_delayed",
    "source_names",
    "source_template",
    "source_url",
]

#: 注册表里的实现类别；与宏观的 `macro_provider` 分开，同名实现互不干扰。
EQUITY_SOURCE_KIND = "equity_source"

#: provider 名 → 进程配置里的地址模板。地址是配置，不是实现细节；新增实现时在这里
#: 加一行，实现本身不写 URL。
_URL_SETTINGS: dict[str, str] = {
    "yahoo": "equity_yahoo_url",
    "stooq": "equity_stooq_url",
}


def build_source(
    name: str,
    *,
    options: Mapping[str, Any],
    client: httpx.Client | None = None,
) -> Any:
    """按名字构造取数实现；名字未登记时 `app.core.get` 抛参数不合法。"""

    factory = get(EQUITY_SOURCE_KIND, name)
    return factory(options=options, client=client)


def source_names() -> list[str]:
    """已登记的 provider 名；配置校验用它列出可选值。"""

    return list_names(EQUITY_SOURCE_KIND)


def _declared(name: str, attribute: str) -> Any:
    """读实现声明的类属性（`bar` / `delayed`），不构造实例、不发请求。"""

    return getattr(get(EQUITY_SOURCE_KIND, name), attribute)


def source_bar(name: str) -> str:
    """该实现实际提供的周期（`1m` / `1d`）。"""

    return str(_declared(name, "bar"))


def source_delayed(name: str) -> bool:
    """该来源是否是延迟行情；未登记的来源按延迟处理，绝不当作实时。"""

    try:
        return bool(_declared(name, "delayed"))
    except Exception:  # 未登记的名字：保守判定为延迟
        return True


def source_template(name: str) -> str | None:
    """该来源的上游地址模板（含 `{symbol}` 占位符）；配置把它交给 provider 拼请求。

    地址是配置事实，与这次有没有抓到数据无关。
    """

    attribute = _URL_SETTINGS.get(name)
    if attribute is None:
        return None
    template = getattr(get_settings(), attribute, "").strip()
    return template or None


def source_url(name: str, symbol: str) -> str | None:
    """该来源对该标的的真实请求地址；接口把它作为「来源」链接返回。

    直接返回模板会让页面出现一个带花括号、点开 404 的链接，因此这里用实现自己的
    地址构造（与抓取时逐字一致：Stooq 的代码是小写 + 市场后缀）。
    """

    template = source_template(name)
    if not template:
        return None
    try:
        return build_source(name, options={"url": template}).url_for(symbol)
    except Exception:  # 未登记的实现：没有可显示的地址
        return None


register(EQUITY_SOURCE_KIND, YahooSource.name)(YahooSource)
register(EQUITY_SOURCE_KIND, StooqSource.name)(StooqSource)
