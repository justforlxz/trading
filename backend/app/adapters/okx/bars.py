"""OKX 周期写法 ↔ 内部枚举的唯一映射点。

OKX 的分钟周期与内部同名，小时/日线用大写（`1H`/`4H`/`1D`）；`1D` 以 UTC+8
为零点（首根 open_time 落在 16:00Z），内部 `1d` 沿用这一锚点，不混用 `1Dutc`。
"""

from app.market.core.bars import normalize_bar

OKX_BAR: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

_INTERNAL_BY_OKX = {value: key for key, value in OKX_BAR.items()}


def to_okx_bar(bar: str) -> str:
    """内部枚举 → OKX 查询参数值。"""

    canonical = normalize_bar(bar)
    try:
        return OKX_BAR[canonical]
    except KeyError as exc:  # pragma: no cover - normalize_bar 已限制取值范围
        raise ValueError(f"bar {bar!r} has no OKX mapping") from exc


def from_okx_bar(value: str) -> str:
    """OKX 返回的 bar 字符串 → 内部枚举（未知写法直接报错，不静默丢弃）。"""

    try:
        return _INTERNAL_BY_OKX[value]
    except KeyError as exc:
        raise ValueError(f"unexpected OKX bar: {value!r}") from exc
