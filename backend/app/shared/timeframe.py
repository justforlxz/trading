"""bar 周期的内部枚举与别名归一化（纯函数，无 IO）。

周期表本身定义在 `app.core.Timeframe`（单一真源），这里只做派生与别名归一化。
对外只接受一批常见别名，并**只**归一化到规范枚举；上游的原始 bar 写法在适配层
映射，业务层不出现上游写法。
"""

from collections.abc import Iterable

from app.core import Timeframe

CANONICAL_BARS: tuple[str, ...] = tuple(item.value for item in Timeframe.ALL)

BAR_SECONDS: dict[str, int] = {item.value: item.seconds for item in Timeframe.ALL}

# 别名 → 内部枚举；查询时大小写不敏感（"1H" / "1D" 是 OKX 写法，也接受）。
ALIASES: dict[str, str] = {
    "1m": "1m",
    "1min": "1m",
    "1minute": "1m",
    "5m": "5m",
    "5min": "5m",
    "15m": "15m",
    "15min": "15m",
    "60m": "1h",
    "1h": "1h",
    "1hour": "1h",
    "240m": "4h",
    "4h": "4h",
    "4hour": "4h",
    "1d": "1d",
    "1day": "1d",
    "24h": "1d",
}

# 滚动保留的 bar（其余周期全量保留）。
ROLLING_BARS: tuple[str, ...] = ("1m", "5m", "15m")


def normalize_bar(value: str) -> str:
    """把外部写法归一化为内部枚举；不支持时抛 `ValueError`。"""

    if not isinstance(value, str):
        raise ValueError(f"unsupported bar: {value!r}")
    key = value.strip().lower()
    try:
        return ALIASES[key]
    except KeyError as exc:
        supported = ", ".join(CANONICAL_BARS)
        raise ValueError(f"unsupported bar {value!r}; supported: {supported}") from exc


def is_rolling_bar(bar: str) -> bool:
    """该周期是否按滚动窗口保留（而非全量）。"""

    return normalize_bar(bar) in ROLLING_BARS


def bar_seconds(bar: str) -> int:
    """周期的秒数（`1d` 按 86400s 处理，见文档对 UTC+8 锚点的说明）。"""

    return BAR_SECONDS[normalize_bar(bar)]


def parse_bars(value: str | Iterable[str]) -> list[str]:
    """解析逗号分隔或可迭代的 bar 列表，去重并保持输入顺序。"""

    items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    for item in items:
        if not item.strip():
            continue
        bar = normalize_bar(item)
        if bar not in result:
            result.append(bar)
    return result
