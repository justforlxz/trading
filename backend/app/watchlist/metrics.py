"""自选行的日线聚合：行情快照、趋势、动量、波动与 K 线覆盖。

全部是纯函数：输入已读出的日线，不读库、不看时钟。指标计算复用
`app.indicators.compute`，与详情页、回测使用同一份算法，不在自选域另写一套。

数据不足时对应字段为 `None`：不补 0、不插值、不把上一根的值冒充当前值。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.core import Bar
from app.indicators import Series, compute

TREND_SHORT_PERIOD = 20
TREND_LONG_PERIOD = 60
RSI_PERIOD = 14
ATR_PERIOD = 14
MIN_QUOTE_BARS = 2

# 与旧接口保持同一口径：涨跌幅 6 位小数，成交额 2 位小数。
_CHANGE_PLACES = Decimal("0.000001")
_TURNOVER_PLACES = Decimal("0.01")
_METRIC_PLACES = Decimal("0.01")
_HUNDRED = Decimal(100)

Trend = Literal["bullish", "bearish", "neutral"]
DataStatus = Literal["ok", "partial", "missing"]


@dataclass(frozen=True, slots=True)
class DailySnapshot:
    """一条自选行的日线快照；每列都来自同一批已收盘日线。"""

    last_price: Decimal | None
    change_pct_24h: Decimal | None
    volume_24h_quote: Decimal | None
    trend: Trend | None
    rsi_14: Decimal | None
    atr_pct_14: Decimal | None
    candle_count: int
    last_candle_at: datetime | None

    @property
    def data_status(self) -> DataStatus:
        """没有 K 线是 `missing`，有 K 线但有指标算不出是 `partial`。"""

        if self.candle_count == 0:
            return "missing"
        if (
            self.last_price is None
            or self.change_pct_24h is None
            or self.trend is None
            or self.rsi_14 is None
            or self.atr_pct_14 is None
        ):
            return "partial"
        return "ok"


def summarize_daily(bars: Sequence[Bar]) -> DailySnapshot:
    """把日线压成一行展示所需的快照；序列按 `open_time` 升序，不信任入参顺序。"""

    ordered = sorted(bars, key=lambda bar: bar.open_time)
    count = len(ordered)
    latest = ordered[-1] if ordered else None
    previous = ordered[-2] if count >= MIN_QUOTE_BARS else None

    change: Decimal | None = None
    turnover: Decimal | None = None
    if latest is not None and previous is not None and previous.close != 0:
        change = ((latest.close - previous.close) / previous.close * _HUNDRED).quantize(
            _CHANGE_PLACES
        )
        turnover = (latest.close * latest.volume).quantize(_TURNOVER_PLACES)

    return DailySnapshot(
        last_price=None if latest is None else latest.close,
        change_pct_24h=change,
        volume_24h_quote=turnover,
        trend=_trend(ordered),
        rsi_14=_metric(_last_value(compute("rsi", ordered, {"period": RSI_PERIOD}), "rsi")),
        atr_pct_14=_atr_pct(ordered),
        candle_count=count,
        last_candle_at=None if latest is None else latest.open_time,
    )


def _trend(bars: Sequence[Bar]) -> Trend | None:
    """收盘价、MA20、MA60 的排列；历史不足 60 根时不给方向。"""

    if len(bars) < TREND_LONG_PERIOD:
        return None
    short = _last_value(compute("sma", bars, {"period": TREND_SHORT_PERIOD}), "sma")
    long = _last_value(compute("sma", bars, {"period": TREND_LONG_PERIOD}), "sma")
    if short is None or long is None:
        return None

    close = bars[-1].close
    if close > short > long:
        return "bullish"
    if close < short < long:
        return "bearish"
    return "neutral"


def _atr_pct(bars: Sequence[Bar]) -> Decimal | None:
    """ATR 占最新收盘价的百分比；收盘价为 0 或历史不足时留空。"""

    if not bars or bars[-1].close == 0:
        return None
    atr = _last_value(compute("atr", bars, {"period": ATR_PERIOD}), "atr")
    if atr is None:
        return None
    return (atr / bars[-1].close * _HUNDRED).quantize(_METRIC_PLACES)


def _metric(value: Decimal | None) -> Decimal | None:
    """展示指标统一保留两位小数；无值时保持 `None`。"""

    return None if value is None else value.quantize(_METRIC_PLACES)


def _last_value(series: Series, name: str) -> Decimal | None:
    """序列最后一点的值；序列为空或该点未定义时返回 `None`。"""

    if not series.points:
        return None
    return series.points[-1].values.get(name)
