"""OKX 报文形状的 K 线与行情快照夹具。

价格由 `sha256(inst_id|bar|open_time)` 派生，跨进程稳定；内置 `hash()`
带进程级随机盐，不能用。行格式与上游一致（倒序、9 列字符串、`confirm`
在末列、1D 开盘 16:00 UTC），由 `tests/fakes/okx/test_row_shape.py`
对照真实录制样本钉死；假 OKX 与适配器测试共用同一份构造函数。
"""

from __future__ import annotations

import hashlib
import time
from decimal import Decimal

# OKX 的 K 线周期写法（上游枚举），1H/4H/1D 必须大写。
BAR_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1H": 3600,
    "4H": 14400,
    "1D": 86400,
}

# OKX 的 1D 边界是 16:00 UTC（美股收盘），不是自然日 00:00。
DAILY_OPEN_OFFSET_SECONDS = 57600

_CENT = Decimal("0.01")


def bar_seconds(bar: str) -> int:
    """返回周期对应的秒数；未知周期直接报错，避免静默按 1m 处理。"""

    try:
        return BAR_SECONDS[bar]
    except KeyError:
        raise ValueError(f"未知 K 线周期:{bar!r}, 可选 {sorted(BAR_SECONDS)}") from None


def align_open_time(timestamp: int, bar: str) -> int:
    """把时间戳对齐到该周期的 K 线开盘边界。"""

    seconds = bar_seconds(bar)
    if bar == "1D":
        return timestamp - (timestamp - DAILY_OPEN_OFFSET_SECONDS) % seconds
    return timestamp - timestamp % seconds


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _price(*parts: object) -> Decimal:
    """10.00 ~ 1009.99 之间的确定性价格。"""

    return (_seed(*parts) % 100_000 / Decimal(100) + Decimal(10)).quantize(_CENT)


def make_candle_row(inst_id: str, bar: str, open_time: int, *, confirm: bool = True) -> list[str]:
    """构造单根 K 线行：`[ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]`。"""

    open_price = _price(inst_id, bar, open_time)
    close_price = _price(inst_id, bar, open_time, "close")
    high_price = max(open_price, close_price) + Decimal("0.37")
    low_price = min(open_price, close_price) - Decimal("0.41")
    volume = (_price(inst_id, bar, open_time, "volume") * 100).quantize(_CENT)
    turnover = (volume * close_price).quantize(_CENT)
    return [
        str(open_time * 1000),
        str(open_price),
        str(high_price.quantize(_CENT)),
        str(low_price.quantize(_CENT)),
        str(close_price),
        str(volume),
        str(turnover),
        str(turnover),
        "1" if confirm else "0",
    ]


def make_candle_rows(
    inst_id: str,
    bar: str,
    *,
    count: int,
    end_time: int | None = None,
    include_incomplete: bool = True,
) -> list[list[str]]:
    """生成倒序（最新在前）的 K 线行；最新一根按 `include_incomplete` 决定是否未收盘。"""

    seconds = bar_seconds(bar)
    newest = align_open_time(int(time.time()) if end_time is None else end_time, bar)
    rows: list[list[str]] = []
    for index in range(count):
        open_time = newest - index * seconds
        confirm = not (include_incomplete and index == 0)
        rows.append(make_candle_row(inst_id, bar, open_time, confirm=confirm))
    return rows


def make_ticker_row(
    inst_id: str, *, inst_type: str = "SPOT", ts: int | None = None
) -> dict[str, str]:
    """构造行情快照行，字段与 OKX `/market/ticker` 一致（全字符串）。"""

    timestamp = int(time.time()) if ts is None else ts
    last = _price(inst_id, "ticker", timestamp // 60)
    bid = last - Decimal("0.01")
    ask = last + Decimal("0.01")
    sod = _price(inst_id, "sod", timestamp // 86400)
    return {
        "instType": inst_type,
        "instId": inst_id,
        "last": str(last),
        "lastSz": "1",
        "askPx": str(ask),
        "askSz": "1",
        "bidPx": str(bid),
        "bidSz": "1",
        "open24h": str(sod),
        "high24h": str(max(ask, sod) + Decimal("1.23")),
        "low24h": str(max(min(bid, sod) - Decimal("1.23"), _CENT)),
        "volCcy24h": "1000",
        "vol24h": "1000",
        "ts": str(timestamp * 1000),
        "sodUtc0": str(sod),
        "sodUtc8": str(sod),
    }
