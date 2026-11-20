"""提醒的纯函数判定：只读已完成的 K 线与完整性报告，不写库。

技术指标复用 `app.indicators` 的同一套实现；价格区间只拿已收盘日线计算。每个候选
都带稳定的 `dedup_key`，由「标的 + 规则 + bar + 方向或阈值」组成，扫描重复执行
不会生成第二条。

`SCAN_MANAGED_RULES` 是「生命周期由提醒扫描维护」的规则集合：扫描只对自己产出的
这些规则判过期。`alert_events` 现在有两个写入方（提醒扫描与事件通知管道），过期扫描
只能处理自己那一半——不在集合里的提醒（例如事件管道的 `price_deviation`）由产出方
自己负责状态，扫描不碰。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.core import Bar
from app.indicators import Series, compute
from app.market import IntegrityReport
from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_MARGIN_USAGE,
    RULE_SINGLE_INSTRUMENT_WEIGHT,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
)

__all__ = [
    "ALERT_SEVERITIES",
    "ALERT_STATUSES",
    "ALERT_TYPES",
    "SCAN_MANAGED_RULES",
    "AlertCandidate",
    "data_gap_candidates",
    "price_range_candidates",
    "technical_candidates",
]

ALERT_TYPES = ("indicator", "price", "risk", "strategy", "data")
ALERT_SEVERITIES = ("info", "warning", "critical")
ALERT_STATUSES = ("pending", "acknowledged", "ignored", "expired")

AlertType = Literal["indicator", "price", "risk", "strategy", "data"]
AlertSeverity = Literal["info", "warning", "critical"]

MA_PERIOD = 20
RSI_PERIOD = 14
TREND_LONG_PERIOD = 60
RANGE_WINDOW = 20
PROXIMITY_PCT = Decimal("1")
RSI_LOWER = Decimal("30")
RSI_UPPER = Decimal("70")
TECHNICAL_RULE_VERSION = "indicator-v1"
PRICE_RULE_VERSION = "range-v1"
DATA_RULE_VERSION = "integrity-v1"

#: 扫描自己产出的规则：技术、价格、数据与风险四类候选的全部 `rule_id`。
#: 只有这些规则的生命周期归扫描管；别的产出方写入的提醒不在其中，扫描不改它们的状态。
SCAN_MANAGED_RULES: frozenset[str] = frozenset(
    {
        "ma20_cross",
        "rsi_zone",
        "trend_change",
        "near_20d_high",
        "near_20d_low",
        "candle_gap",
        RULE_STOP_MISSING,
        RULE_STOP_DISTANCE,
        RULE_HIGH_LEVERAGE,
        RULE_SINGLE_INSTRUMENT_WEIGHT,
        RULE_MARGIN_USAGE,
    }
)

_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    """一条待写入的提醒；`dedup_key` 由构造方给出，服务层只负责落库。"""

    type: AlertType
    severity: AlertSeverity
    instrument_id: str | None
    rule_id: str
    rule_version: str
    title: str
    detail: str
    dedup_key: str
    triggered_at: datetime
    payload: dict[str, object] = field(default_factory=dict)
    expires_at: datetime | None = None


def technical_candidates(
    symbol: str,
    bars: list[Bar],
    *,
    moment: datetime,
) -> list[AlertCandidate]:
    """MA20 穿越、RSI 进入观察区、趋势状态变化；只用已收盘 K 线。"""

    ordered = sorted((bar for bar in bars if bar.confirm), key=lambda bar: bar.open_time)
    if len(ordered) < 2:
        return []
    latest = ordered[-1]
    bar_key = latest.open_time.isoformat()
    closes = [bar.close for bar in ordered]
    found: list[AlertCandidate] = []

    if len(ordered) >= MA_PERIOD:
        sma = compute("sma", ordered, {"period": MA_PERIOD})
        current_ma = _value(sma, -1)
        previous_ma = _value(sma, -2)
        if current_ma is not None and previous_ma is not None:
            previous_close = closes[-2]
            if previous_close >= previous_ma and latest.close < current_ma:
                found.append(
                    _candidate(
                        "ma20_cross",
                        symbol,
                        bar_key,
                        "down",
                        "收盘价跌破 MA20",
                        f"{symbol} 收盘价 {latest.close} 跌破 MA20（{_number(current_ma)}）",
                        moment,
                        {"close": str(latest.close), "ma20": str(current_ma)},
                    )
                )
            elif previous_close <= previous_ma and latest.close > current_ma:
                found.append(
                    _candidate(
                        "ma20_cross",
                        symbol,
                        bar_key,
                        "up",
                        "收盘价站上 MA20",
                        f"{symbol} 收盘价 {latest.close} 站上 MA20（{_number(current_ma)}）",
                        moment,
                        {"close": str(latest.close), "ma20": str(current_ma)},
                    )
                )

    if len(ordered) >= RSI_PERIOD + 1:
        rsi = compute("rsi", ordered, {"period": RSI_PERIOD})
        current_rsi = _value(rsi, -1)
        previous_rsi = _value(rsi, -2)
        if current_rsi is not None and previous_rsi is not None:
            if previous_rsi >= RSI_LOWER and current_rsi < RSI_LOWER:
                found.append(
                    _candidate(
                        "rsi_zone",
                        symbol,
                        bar_key,
                        "oversold",
                        "RSI 进入超卖观察区",
                        f"{symbol} RSI14 从 {_number(previous_rsi)} 降到 {_number(current_rsi)}",
                        moment,
                        {"rsi14": str(current_rsi), "threshold": str(RSI_LOWER)},
                    )
                )
            elif previous_rsi <= RSI_UPPER and current_rsi > RSI_UPPER:
                found.append(
                    _candidate(
                        "rsi_zone",
                        symbol,
                        bar_key,
                        "overbought",
                        "RSI 进入超买观察区",
                        f"{symbol} RSI14 从 {_number(previous_rsi)} 升到 {_number(current_rsi)}",
                        moment,
                        {"rsi14": str(current_rsi), "threshold": str(RSI_UPPER)},
                    )
                )

    if len(ordered) >= TREND_LONG_PERIOD + 1:
        previous_trend = _trend(ordered[:-1])
        current_trend = _trend(ordered)
        if (
            previous_trend is not None
            and current_trend is not None
            and previous_trend != current_trend
        ):
            found.append(
                _candidate(
                    "trend_change",
                    symbol,
                    bar_key,
                    current_trend,
                    "趋势状态变化",
                    f"{symbol} 趋势由 {previous_trend} 变为 {current_trend}",
                    moment,
                    {"from": previous_trend, "to": current_trend},
                )
            )

    return found


def price_range_candidates(
    symbol: str,
    bars: list[Bar],
    *,
    moment: datetime,
) -> list[AlertCandidate]:
    """收盘价距离前 20 日区间高低点小于阈值；区间不含最新一根。"""

    ordered = sorted((bar for bar in bars if bar.confirm), key=lambda bar: bar.open_time)
    if len(ordered) < RANGE_WINDOW + 1:
        return []
    latest = ordered[-1]
    previous = ordered[-RANGE_WINDOW - 1 : -1]
    high = max(bar.high for bar in previous)
    low = min(bar.low for bar in previous)
    bar_key = latest.open_time.isoformat()
    found: list[AlertCandidate] = []

    high_distance = _distance_pct(latest.close, high)
    if high > 0 and high_distance is not None and high_distance < PROXIMITY_PCT:
        found.append(
            _candidate(
                "near_20d_high",
                symbol,
                bar_key,
                "high",
                "接近 20 日高点",
                f"{symbol} 收盘价 {latest.close} 距 20 日高点 {high} 仅 {_number(high_distance)}%",
                moment,
                {
                    "close": str(latest.close),
                    "high_20d": str(high),
                    "distance_pct": str(high_distance),
                },
                type_="price",
                rule_version=PRICE_RULE_VERSION,
            )
        )
    low_distance = _distance_pct(low, latest.close)
    if low > 0 and low_distance is not None and low_distance < PROXIMITY_PCT:
        found.append(
            _candidate(
                "near_20d_low",
                symbol,
                bar_key,
                "low",
                "接近 20 日低点",
                f"{symbol} 收盘价 {latest.close} 距 20 日低点 {low} 仅 {_number(low_distance)}%",
                moment,
                {
                    "close": str(latest.close),
                    "low_20d": str(low),
                    "distance_pct": str(low_distance),
                },
                type_="price",
                rule_version=PRICE_RULE_VERSION,
            )
        )
    return found


def data_gap_candidates(
    symbol: str,
    report: IntegrityReport,
    *,
    moment: datetime,
) -> list[AlertCandidate]:
    """K 线完整性报告里有缺失时生成一条数据提醒；同一缺口只报一次。"""

    if report.missing <= 0:
        return []
    if report.gaps:
        gap = report.gaps[0]
        start, end = gap.start, gap.end
        missing = gap.missing
        dedup_bar = start.isoformat()
        detail = f"{symbol} 日线在 {start.isoformat()} 至 {end.isoformat()} 缺失 {missing} 根"
    else:
        start = report.start
        end = report.end
        missing = report.missing
        dedup_bar = "unknown" if start is None else start.isoformat()
        detail = f"{symbol} 日线完整性报告缺失 {missing} 根"
    return [
        AlertCandidate(
            type="data",
            severity="warning",
            instrument_id=symbol,
            rule_id="candle_gap",
            rule_version=DATA_RULE_VERSION,
            title="日线数据存在缺口",
            detail=detail,
            dedup_key=f"data|candle_gap|{symbol}|{dedup_bar}",
            triggered_at=moment,
            payload={
                "missing": missing,
                "start": None if start is None else start.isoformat(),
                "end": None if end is None else end.isoformat(),
            },
        )
    ]


def _candidate(
    rule_id: str,
    symbol: str,
    bar_key: str,
    direction: str,
    title: str,
    detail: str,
    moment: datetime,
    payload: dict[str, object],
    *,
    type_: AlertType = "indicator",
    severity: AlertSeverity = "info",
    rule_version: str = TECHNICAL_RULE_VERSION,
) -> AlertCandidate:
    return AlertCandidate(
        type=type_,
        severity=severity,
        instrument_id=symbol,
        rule_id=rule_id,
        rule_version=rule_version,
        title=title,
        detail=detail,
        dedup_key=f"{type_}|{rule_id}|{symbol}|{bar_key}|{direction}",
        triggered_at=moment,
        payload=payload,
    )


def _value(series: Series, index: int) -> Decimal | None:
    if not series.points:
        return None
    try:
        point = series.points[index]
    except IndexError:
        return None
    return point.values.get(
        series.name if series.name in point.values else next(iter(point.values))
    )


def _trend(bars: list[Bar]) -> str | None:
    if len(bars) < TREND_LONG_PERIOD:
        return None
    short = _value(compute("sma", bars, {"period": MA_PERIOD}), -1)
    long = _value(compute("sma", bars, {"period": TREND_LONG_PERIOD}), -1)
    if short is None or long is None:
        return None
    close = bars[-1].close
    if close > short > long:
        return "bullish"
    if close < short < long:
        return "bearish"
    return "neutral"


def _distance_pct(a: Decimal, b: Decimal) -> Decimal | None:
    if b == 0:
        return None
    return (abs(a - b) / b * _HUNDRED).quantize(Decimal("0.01"))


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f")
