"""宏观数据源配置的解析：`settings.data_sources.macro` → 抓取所需的 provider 与地址。

配置形状（缺项用 `DEFAULT_PROVIDERS` 补齐，见 `app/settings` 的 `DEFAULT_DATA_SOURCES`）：

```json
{
  "series": {
    "us10y": {"minute": "yahoo", "daily": "treasury"},
    "vix": {"minute": "yahoo", "daily": "cboe"}
  },
  "scheduler": {"minute": "1m"}
}
```

`series` 决定每个序列每个粒度用哪个 provider；上游地址跟 OKX 一样只从
`app/config.py`（环境变量）读取，抓取实现里不写 URL。因此「换源」只要改 `series`，
调用方代码不动。

配置不合法（provider 未登记、缺地址、周期不在允许值内）时抛 `ValidationError`：这是
用户可以改配置修好的失败，不是上游故障，不能降级成缓存值糊过去。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings
from app.core import ValidationError
from app.macro.providers import provider_names
from app.macro.series import DEFAULT_PROVIDERS, SERIES, SERIES_BY_ID, SERIES_PROVIDERS

__all__ = [
    "ALLOWED_INTERVALS",
    "DEFAULT_INTERVAL",
    "MacroConfig",
    "SeriesUnit",
    "resolve_config",
    "validate_series_override",
]

#: 允许的调度周期；不支持「定点时刻」，避免把周期配置写成 cron 语义。
ALLOWED_INTERVALS: dict[str, int] = {"1m": 60, "5m": 300}
DEFAULT_INTERVAL = "1m"


@dataclass(frozen=True, slots=True)
class SeriesUnit:
    """一个抓取单元：序列 + 粒度 + 当前配置的 provider。"""

    series_id: str
    granularity: str
    provider: str


@dataclass(frozen=True, slots=True)
class MacroConfig:
    """一次调度需要的全部配置：序列→provider、provider→地址、周期。"""

    series: Mapping[str, Mapping[str, str]]
    providers: Mapping[str, Mapping[str, Any]]
    interval: str
    interval_seconds: int

    def units(self) -> tuple[SeriesUnit, ...]:
        """按序列清单顺序展开全部抓取单元；同一 provider 可服务多个粒度。"""

        units: list[SeriesUnit] = []
        for spec in SERIES:
            for granularity in spec.granularities:
                provider = self.series[spec.series_id][granularity]
                units.append(SeriesUnit(spec.series_id, granularity, provider))
        return tuple(units)

    def provider_for(self, series_id: str, granularity: str) -> str:
        return self.series[series_id][granularity]

    def options(self, provider: str) -> Mapping[str, Any]:
        return self.providers[provider]


def validate_series_override(series: Mapping[str, Mapping[str, str | None]]) -> None:
    """校验设置里提交的「序列 → 粒度 → provider」覆盖，非法名当场拒绝。

    校验放在写入路径上：否则任意 provider 名都能保存成功，等下一次读配置时才炸，
    首页宏观区整体报错、调度器每轮空转，用户只能手工改回来。
    """

    available = sorted(provider_names())
    for series_id, entry in series.items():
        spec = SERIES_BY_ID.get(series_id)
        if spec is None:
            raise ValidationError(
                f"未登记的宏观序列 {series_id!r}; 可选: {', '.join(SERIES_BY_ID)}"
            )
        for granularity, name in entry.items():
            if name is None:
                continue
            if granularity not in spec.granularities:
                raise ValidationError(
                    f"宏观序列 {series_id} 没有 {granularity!r} 粒度; "
                    f"可选: {', '.join(spec.granularities)}"
                )
            allowed = SERIES_PROVIDERS.get(series_id, {}).get(granularity, ())
            if name not in allowed:
                raise ValidationError(
                    f"宏观序列 {series_id} 的 {granularity} 不支持 provider {name!r}; "
                    f"可选: {', '.join(allowed) or '(无)'}（已实现: {', '.join(available)}）"
                )


def _group(data_sources: Mapping[str, Any]) -> Mapping[str, Any]:
    macro = data_sources.get("macro")
    return macro if isinstance(macro, Mapping) else {}


def _text(group: Any, key: str) -> str:
    if not isinstance(group, Mapping):
        return ""
    value = group.get(key)
    return value.strip() if isinstance(value, str) else ""


def _provider_options(name: str, runtime: Settings) -> Mapping[str, Any]:
    """provider 名 → 上游配置。地址是配置，不是实现细节。"""

    if name == "treasury":
        return {"url": runtime.macro_treasury_url}
    if name == "cboe":
        return {"url": runtime.macro_cboe_url}
    if name == "yahoo":
        return {
            "urls": {
                "us10y": runtime.macro_yahoo_tnx_url,
                "vix": runtime.macro_yahoo_vix_url,
            }
        }
    raise ValidationError(f"宏观 provider {name} 没有配置上游地址")


def resolve_config(data_sources: Mapping[str, Any]) -> MacroConfig:
    """把设置文档里的宏观分组解析成可执行的配置；不合法直接报错。"""

    macro = _group(data_sources)
    configured = macro.get("series")
    configured = configured if isinstance(configured, Mapping) else {}

    available = set(provider_names())
    series: dict[str, dict[str, str]] = {}
    for spec in SERIES:
        entry = configured.get(spec.series_id)
        entry = entry if isinstance(entry, Mapping) else {}
        per_granularity: dict[str, str] = {}
        for granularity in spec.granularities:
            name = _text(entry, granularity) or DEFAULT_PROVIDERS[spec.series_id][granularity]
            if name not in available:
                raise ValidationError(
                    f"宏观序列 {spec.series_id} 的 {granularity} provider {name!r} 未登记; "
                    f"已实现: {', '.join(sorted(available))}"
                )
            allowed = SERIES_PROVIDERS[spec.series_id].get(granularity, ())
            if name not in allowed:
                raise ValidationError(
                    f"宏观序列 {spec.series_id} 的 {granularity} 不支持 provider {name!r}; "
                    f"可选: {', '.join(allowed) or '(无)'}"
                )
            per_granularity[granularity] = name
        series[spec.series_id] = per_granularity

    runtime = get_settings()
    providers: dict[str, Mapping[str, Any]] = {}
    for name in sorted({item for entry in series.values() for item in entry.values()}):
        providers[name] = _provider_options(name, runtime)

    interval = _text(macro.get("scheduler"), "minute") or DEFAULT_INTERVAL
    if interval not in ALLOWED_INTERVALS:
        raise ValidationError(
            f"宏观调度周期 {interval!r} 不支持; 可选: {', '.join(ALLOWED_INTERVALS)}"
        )
    return MacroConfig(
        series=series,
        providers=providers,
        interval=interval,
        interval_seconds=ALLOWED_INTERVALS[interval],
    )
