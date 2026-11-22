"""`settings.data_sources.equity` 的解析：provider 名、标的清单与调度周期。

配置形状（缺项用默认值补齐，见 `app/settings` 的 `DEFAULT_DATA_SOURCES`）：

```json
{
  "provider": "yahoo",
  "symbols": ["SPY", "QQQ"],
  "scheduler": {"minute": "1m"}
}
```

`provider` 决定用哪个实现；上游地址跟 OKX、宏观一样只从 `app/config.py`（环境变量）
读取，实现里不写 URL。因此「换源」只要改这一个字段，调用方代码不动。

**周期不在这里配置**：它由 provider 实现声明（Yahoo 1 分钟、Stooq 日线），配置切到
哪个实现就落哪个周期。让用户在设置里选一个源不提供的周期，只会在落库时静默造假。

配置不合法（provider 未登记、标的为空、周期不在允许值内）时抛 `ValidationError`：
这是用户可以改配置修好的失败，不是上游故障，不能降级成缓存值糊过去。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core import ValidationError
from app.equity.providers import provider_bar, provider_names, provider_template

__all__ = [
    "ALLOWED_INTERVALS",
    "DEFAULT_INTERVAL",
    "DEFAULT_PROVIDER",
    "DEFAULT_SYMBOLS",
    "MAX_SYMBOL_LENGTH",
    "EquityConfig",
    "clean_symbols",
    "resolve_config",
    "validate_equity_override",
]

#: 允许的调度周期；不支持「定点时刻」，避免把周期配置写成 cron 语义。
ALLOWED_INTERVALS: dict[str, int] = {"1m": 60, "5m": 300}
DEFAULT_INTERVAL = "1m"
DEFAULT_PROVIDER = "yahoo"
#: 默认标的：两个美股指数 ETF。它们只出现在首页「市场概况」，不进关注列表。
DEFAULT_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ")
#: 标的名进 `candles.symbol`（`String(64)`），这里按上游代码的常见长度收紧。
MAX_SYMBOL_LENGTH = 16


@dataclass(frozen=True, slots=True)
class EquityConfig:
    """一次调度需要的全部配置：provider 名、标的清单、周期与调度周期。"""

    provider: str
    symbols: tuple[str, ...]
    bar: str
    interval: str
    interval_seconds: int
    #: 上游地址模板（含 `{symbol}`）；未配置时为 `None`，抓取时如实报错。
    url: str | None

    def options(self) -> Mapping[str, Any]:
        """交给 provider 的上游配置；实现只认 `url`。"""

        return {"url": self.url} if self.url else {}


def _group(data_sources: Mapping[str, Any]) -> Mapping[str, Any]:
    equity = data_sources.get("equity")
    return equity if isinstance(equity, Mapping) else {}


def _text(group: Any, key: str) -> str:
    if not isinstance(group, Mapping):
        return ""
    value = group.get(key)
    return value.strip() if isinstance(value, str) else ""


def clean_symbols(value: Any) -> tuple[str, ...]:
    """标的清单：去空白、去重、保持提交顺序；非字符串项丢弃。"""

    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    cleaned = (item.strip() for item in value if isinstance(item, str))
    return tuple(dict.fromkeys(item for item in cleaned if item))


def validate_equity_override(
    *,
    provider: str | None = None,
    symbols: Sequence[str] | None = None,
) -> None:
    """校验设置里提交的美股分组；非法值当场拒绝。

    校验放在写入路径上：provider 名写错却保存成功，要等下一次读配置才炸，首页美股区
    整体报错、调度器每轮空转，用户只能手工改回来。
    """

    if provider is not None:
        available = provider_names()
        if provider not in available:
            raise ValidationError(
                f"未登记的美股 provider {provider!r}; 已实现: {', '.join(available) or '(空)'}"
            )
    if symbols is not None:
        if not symbols:
            raise ValidationError("美股标的清单不能为空")
        for symbol in symbols:
            if not symbol:
                raise ValidationError("美股标的名不能为空")
            if len(symbol) > MAX_SYMBOL_LENGTH:
                raise ValidationError(f"美股标的名过长: {symbol!r}")
            if any(item.isspace() for item in symbol):
                raise ValidationError(f"美股标的名不能包含空白: {symbol!r}")


def resolve_config(data_sources: Mapping[str, Any]) -> EquityConfig:
    """把设置文档里的美股分组解析成可执行的配置；不合法直接报错。"""

    equity = _group(data_sources)
    available = provider_names()
    provider = _text(equity, "provider") or DEFAULT_PROVIDER
    if provider not in available:
        raise ValidationError(
            f"美股 provider {provider!r} 未登记; 已实现: {', '.join(available) or '(空)'}"
        )

    symbols = clean_symbols(equity.get("symbols")) or DEFAULT_SYMBOLS
    validate_equity_override(provider=provider, symbols=symbols)

    interval = _text(equity.get("scheduler"), "minute") or DEFAULT_INTERVAL
    if interval not in ALLOWED_INTERVALS:
        raise ValidationError(
            f"美股调度周期 {interval!r} 不支持; 可选: {', '.join(ALLOWED_INTERVALS)}"
        )

    return EquityConfig(
        provider=provider,
        symbols=symbols,
        bar=provider_bar(provider),
        interval=interval,
        interval_seconds=ALLOWED_INTERVALS[interval],
        url=provider_template(provider),
    )
