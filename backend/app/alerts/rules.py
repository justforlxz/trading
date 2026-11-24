"""提醒的纯函数判定：只读已完成的 K 线、收益率读数与完整性报告，不写库。

技术指标复用 `app.indicators` 的同一套实现；价格区间只拿已收盘日线计算。每个候选
都带稳定的 `dedup_key`，由「标的 + 规则 + bar + 方向或阈值」组成，扫描重复执行
不会生成第二条。

大盘异动与组合异动的去重键**不带 bar**，改带「方向 + 级别」：这两类规则要的是「进入
某个级别时通知一次，同级持续不重复」。带 bar 的话每到新的一天就是一条新提醒，连续
急跌三天会响三次。级别下降（或回落到阈值内）时提醒由扫描标为 `expired`，再次跨过同
一级别即可用原来的键重新激活——这正好是「回落后再跨过才再发」。

`SCAN_MANAGED_RULES` 是「生命周期由提醒扫描维护」的规则集合：扫描只对自己产出的
这些规则判过期。`alert_events` 现在有两个写入方（提醒扫描与事件通知管道），过期扫描
只能处理自己那一半——不在集合里的提醒（例如事件管道的 `price_deviation`）由产出方
自己负责状态，扫描不碰。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from typing import Literal

from app.core import Bar
from app.indicators import Series, compute
from app.market import MARKET_INDEXES, IntegrityReport, MarketIndex
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
    "MARKET_ATR_PERIOD",
    "MARKET_SCAN_RULES",
    "SCAN_MANAGED_RULES",
    "SPREAD_RULE_ID",
    "US10Y_RULE_ID",
    "WATCHLIST_RULE_ID",
    "AlertCandidate",
    "atr_pct",
    "data_gap_candidates",
    "market_index_candidates",
    "market_rule_id",
    "price_range_candidates",
    "spread_candidates",
    "technical_candidates",
    "us10y_candidates",
    "watchlist_candidates",
]

ALERT_TYPES = ("indicator", "price", "risk", "strategy", "data", "market", "watchlist")
ALERT_SEVERITIES = ("info", "warning", "critical")
ALERT_STATUSES = ("pending", "acknowledged", "ignored", "expired")

AlertType = Literal["indicator", "price", "risk", "strategy", "data", "market", "watchlist"]
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

#: 大盘异动的阈值一律以 ATR 倍数表达：三个指数的日常波动差三倍，固定百分比在费半上
#: 六十个交易日会响 29 次（等于没有提醒），在高波板块上完全没有区分度。
MARKET_ATR_PERIOD = 20
#: ATR 倍数 → 级别，从严重到轻微排列；第一个满足的就是结果。
MARKET_ATR_LEVELS: tuple[tuple[Decimal, AlertSeverity], ...] = (
    (Decimal("4"), "critical"),
    (Decimal("2.5"), "warning"),
    (Decimal("1.5"), "info"),
)
#: 收益率单日变化（基点的绝对值）→ 级别，同样从严重到轻微排列。
RATE_BP_LEVELS: tuple[tuple[Decimal, AlertSeverity], ...] = (
    (Decimal("30"), "critical"),
    (Decimal("20"), "warning"),
    (Decimal("10"), "info"),
)
#: 2Y→10Y 利差单日变化（基点）达到这个数才提示；只有一档。
SPREAD_CHANGE_BP = Decimal("10")
#: 组合异动：下跌标的占比下限，以及平均跌幅要达到组合自身 ATR 的多少倍。
WATCHLIST_DECLINER_SHARE = Decimal("0.7")
WATCHLIST_ATR_MULTIPLE = Decimal("1.5")
WATCHLIST_ATR_PERIOD = 20
MARKET_RULE_VERSION = "market-atr-v1"
RATE_RULE_VERSION = "macro-bp-v1"
WATCHLIST_RULE_VERSION = "watchlist-breadth-v1"

#: 收益率与利差两条规则不是单标的规则，规则标识写死在这里，不按指数生成。
US10Y_RULE_ID = "market_us10y_bp"
SPREAD_RULE_ID = "market_2s10s_bp"
WATCHLIST_RULE_ID = "watchlist_breadth"


def market_rule_id(index_key: str) -> str:
    """某个指数的单日涨跌规则标识；键取 `MarketIndex.key`，界面与日志里同一套说法。"""

    return f"market_{index_key}_change"


#: 大盘与组合规则：由行情调度收到新数据后单独评估（`scan_market_alerts`）。
MARKET_SCAN_RULES: frozenset[str] = frozenset(
    {
        US10Y_RULE_ID,
        SPREAD_RULE_ID,
        WATCHLIST_RULE_ID,
        *(market_rule_id(index.key) for index in MARKET_INDEXES),
    }
)

#: 单标的规则：技术、价格、数据与风险四类，只由完整扫描（`scan_alerts`）评估。
_SECURITY_SCAN_RULES: frozenset[str] = frozenset(
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

#: 扫描自己产出的规则：六类候选的全部 `rule_id`。只有这些规则的生命周期归扫描管；
#: 别的产出方写入的提醒不在其中，扫描不改它们的状态。
#:
#: 判过期还必须带上「这一轮实际评估了哪些规则」（`MARKET_SCAN_RULES` /
#: `_SECURITY_SCAN_RULES` 或两者之和）：只评估大盘的那一轮不能把没评估过的技术、风险
#: 提醒当成「条件已恢复」，那会把用户待处理的提醒全部清空。
SCAN_MANAGED_RULES: frozenset[str] = _SECURITY_SCAN_RULES | MARKET_SCAN_RULES

_HUNDRED = Decimal(100)

#: 提醒正文里的级别中文名；与前端、推送渲染同一套措辞。
_SEVERITY_NAMES: dict[str, str] = {"info": "提示", "warning": "警告", "critical": "紧急"}


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


def atr_pct(bars: Sequence[Bar], period: int = MARKET_ATR_PERIOD) -> Decimal | None:
    """日线 ATR 占最新收盘价的百分比。

    算法与 `app.indicators` 的 `atr` 是同一份实现：真实波幅
    `TR = max(当根高低差, |当根最高 - 前一根收盘|, |当根最低 - 前一根收盘|)`，
    前 `period` 个 TR 的算术平均作为起点，之后按 Wilder 公式逐日平滑；
    `ATR% = ATR ÷ 最新收盘价 × 100`。至少要 `period + 1` 根：第 0 根没有前收盘，
    它的 TR 只能用高低差，单靠它做起点会把波动低估。
    """

    ordered = _confirmed(bars)
    if len(ordered) < period + 1 or ordered[-1].close <= 0:
        return None
    series = compute("atr", ordered, {"period": period})
    atr = _value(series, -1)
    if atr is None or atr <= 0:
        return None
    return atr / ordered[-1].close * _HUNDRED


def market_index_candidates(
    index: MarketIndex,
    bars: Sequence[Bar],
    *,
    moment: datetime,
) -> list[AlertCandidate]:
    """一个指数的单日涨跌是否跨过 ATR 倍数门槛。

    基线只取异动日**之前**的 20 个交易日：把异动当天算进基线会自我稀释——当天波动
    越大基线越高，最大的那根行情反而被判成最轻的级别。
    """

    ordered = _confirmed(bars)
    if len(ordered) < MARKET_ATR_PERIOD + 2:
        return []
    latest, previous = ordered[-1], ordered[-2]
    if previous.close <= 0:
        return []
    atr = atr_pct(ordered[:-1])
    if atr is None:
        return []
    change_pct = (latest.close - previous.close) / previous.close * _HUNDRED
    multiple = abs(change_pct) / atr
    level = _level_for(multiple, MARKET_ATR_LEVELS)
    if level is None:
        return []
    rule_id = market_rule_id(index.key)
    direction = "up" if change_pct > 0 else "down"
    verb = "上涨" if direction == "up" else "下跌"
    change_text = _fixed(abs(change_pct))
    return [
        AlertCandidate(
            type="market",
            severity=level,
            instrument_id=None,
            rule_id=rule_id,
            rule_version=MARKET_RULE_VERSION,
            title=f"{index.name} 单日{verb} {change_text}%",
            detail=(
                f"{index.name}（{index.symbol}）单日{verb} {change_text}%，"
                f"为 ATR{MARKET_ATR_PERIOD}（{_fixed(atr)}%）的 {_fixed(multiple)} 倍，"
                f"达到{_SEVERITY_NAMES[level]}级"
            ),
            dedup_key=f"market|{rule_id}|{index.symbol}|{direction}|{level}",
            triggered_at=moment,
            payload={
                "index": index.key,
                "symbol": index.symbol,
                "name": index.name,
                "bar": latest.open_time.date().isoformat(),
                "close": str(latest.close),
                "previous_close": str(previous.close),
                "change_pct": change_text,
                "atr20_pct": _fixed(atr),
                "atr_multiple": _fixed(multiple),
            },
        )
    ]


def us10y_candidates(
    *,
    change_pp: Decimal,
    value: Decimal,
    trading_day: date,
    moment: datetime,
) -> list[AlertCandidate]:
    """10Y 收益率单日变化是否跨过基点门槛；`change_pp` 是百分点，乘 100 换成基点。"""

    change_bp = change_pp * _HUNDRED
    level = _level_for(abs(change_bp), RATE_BP_LEVELS)
    if level is None:
        return []
    direction = "up" if change_bp > 0 else "down"
    verb = "上行" if direction == "up" else "下行"
    move_text = _fixed(abs(change_bp), "0.1")
    return [
        AlertCandidate(
            type="market",
            severity=level,
            instrument_id=None,
            rule_id=US10Y_RULE_ID,
            rule_version=RATE_RULE_VERSION,
            title=f"10Y 收益率单日{verb} {move_text}bp",
            detail=(
                f"美国 10 年期国债收益率由 {_fixed(value - change_pp, '0.001')}% 变为 "
                f"{_fixed(value, '0.001')}%，单日{verb} {move_text}bp，"
                f"达到{_SEVERITY_NAMES[level]}级"
            ),
            dedup_key=f"market|{US10Y_RULE_ID}|us10y|{direction}|{level}",
            triggered_at=moment,
            payload={
                "series_id": "us10y",
                "trading_day": trading_day.isoformat(),
                "value": str(value),
                "change_bp": _fixed(change_bp, "0.1"),
            },
        )
    ]


def spread_candidates(
    *,
    current_bp: Decimal,
    previous_bp: Decimal,
    trading_day: date,
    moment: datetime,
) -> list[AlertCandidate]:
    """2Y→10Y 利差：新形成倒挂、解除倒挂，或单日变化达到 10bp。

    倒挂/解除本身就是状态跃迁，优先作为这一条提醒的理由；同一天既有倒挂又超过 10bp
    时只发「新形成倒挂」一条，不拆成两条。
    """

    change_bp = current_bp - previous_bp
    if previous_bp >= 0 > current_bp:
        direction, title, reason = "inverted", "2Y→10Y 新形成倒挂", "新形成倒挂"
    elif previous_bp < 0 <= current_bp:
        direction, title, reason = "uninverted", "2Y→10Y 解除倒挂", "解除倒挂"
    elif abs(change_bp) >= SPREAD_CHANGE_BP:
        widening = change_bp > 0
        direction = "widening" if widening else "narrowing"
        verb = "走阔" if widening else "收窄"
        title = f"2Y→10Y 利差单日{verb} {_fixed(abs(change_bp), '0.1')}bp"
        reason = f"单日{verb} {_fixed(abs(change_bp), '0.1')}bp"
    else:
        return []
    return [
        AlertCandidate(
            type="market",
            severity="info",
            instrument_id=None,
            rule_id=SPREAD_RULE_ID,
            rule_version=RATE_RULE_VERSION,
            title=title,
            detail=(
                f"2Y→10Y 利差由 {_fixed(previous_bp, '0.1')}bp 变为 "
                f"{_fixed(current_bp, '0.1')}bp，{reason}"
            ),
            dedup_key=f"market|{SPREAD_RULE_ID}|2s10s|{direction}|info",
            triggered_at=moment,
            payload={
                "series_id": "us2y-us10y",
                "trading_day": trading_day.isoformat(),
                "current_bp": _fixed(current_bp, "0.1"),
                "previous_bp": _fixed(previous_bp, "0.1"),
                "inverted": current_bp < 0,
            },
        )
    ]


def watchlist_candidates(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    *,
    moment: datetime,
) -> list[AlertCandidate]:
    """自选整体走弱：至少七成标的下跌，且平均跌幅达到组合自身日波动的 1.5 倍。

    组合没有高低价，组合 ATR 用「等权组合日收益」的真实波幅代替：每天的组合收益是
    当日有数据标的的等权平均，组合 ATR% 取异动日**之前** 20 个交易日组合收益绝对值
    的平均。等权的意义是不让单一标的的暴涨暴跌决定整组的波动。
    """

    returns = {symbol: _daily_returns(bars) for symbol, bars in bars_by_symbol.items()}
    usable = {symbol: series for symbol, series in returns.items() if series}
    if len(usable) < 2:
        return []
    days = sorted({day for series in usable.values() for day in series})
    alert_day = days[-1]
    day_returns = {
        symbol: series[alert_day] for symbol, series in usable.items() if alert_day in series
    }
    participants = len(day_returns)
    if participants < 2:
        return []
    decliners = [value for value in day_returns.values() if value < 0]
    if not decliners:
        return []
    share = Decimal(len(decliners)) / Decimal(participants)
    if share < WATCHLIST_DECLINER_SHARE:
        return []
    average_decline = sum(decliners) / Decimal(len(decliners))
    atr = _portfolio_atr_pct(usable, before=alert_day)
    if atr is None:
        return []
    multiple = abs(average_decline) / atr
    if multiple < WATCHLIST_ATR_MULTIPLE:
        return []
    return [
        AlertCandidate(
            type="watchlist",
            severity="info",
            instrument_id=None,
            rule_id=WATCHLIST_RULE_ID,
            rule_version=WATCHLIST_RULE_VERSION,
            title="自选组合整体走弱",
            detail=(
                f"自选 {participants} 个标的里 {len(decliners)} 个下跌"
                f"（{_fixed(share * _HUNDRED)}%），平均跌幅 {_fixed(abs(average_decline))}%，"
                f"为组合 ATR{WATCHLIST_ATR_PERIOD}（{_fixed(atr)}%）的 {_fixed(multiple)} 倍"
            ),
            dedup_key=f"watchlist|{WATCHLIST_RULE_ID}|all|down|info",
            triggered_at=moment,
            payload={
                "bar": alert_day.isoformat(),
                "participants": participants,
                "decliners": len(decliners),
                "decline_share": _fixed(share, "0.001"),
                "average_decline_pct": _fixed(abs(average_decline)),
                "portfolio_atr20_pct": _fixed(atr),
                "atr_multiple": _fixed(multiple),
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


def _fixed(value: Decimal, quantum: str = "0.01") -> str:
    """按固定小数位显示；不长出 `4.300000000001` 这种尾巴。"""

    return format(value.quantize(Decimal(quantum)), "f")


def _confirmed(bars: Sequence[Bar]) -> list[Bar]:
    """只留已收盘 K 线并按 `open_time` 排序：入参顺序与未收盘的最后一根都不能影响判定。"""

    return sorted((bar for bar in bars if bar.confirm), key=lambda bar: bar.open_time)


def _level_for(
    magnitude: Decimal,
    bands: Sequence[tuple[Decimal, AlertSeverity]],
) -> AlertSeverity | None:
    """按「从严重到轻微」的阈值表取级别；一个都没跨过时给 `None`（不发提醒）。"""

    for threshold, level in bands:
        if magnitude >= threshold:
            return level
    return None


def _daily_returns(bars: Sequence[Bar]) -> dict[date, Decimal]:
    """逐交易日的收益率（百分比），键是当天的交易日；缺前一根的天数不产生值。"""

    ordered = _confirmed(bars)
    returns: dict[date, Decimal] = {}
    for previous, current in pairwise(ordered):
        if previous.close <= 0:
            continue
        returns[current.open_time.date()] = (
            (current.close - previous.close) / previous.close * (_HUNDRED)
        )
    return returns


def _portfolio_atr_pct(
    returns: Mapping[str, Mapping[date, Decimal]],
    *,
    before: date,
) -> Decimal | None:
    """等权组合在 `before` 之前 20 个交易日的平均绝对日收益（即组合 ATR%）。

    交易日不够 20 天时给 `None`：用两三天的波动当基线，会把任何一天都判成异动。
    """

    days = sorted({day for series in returns.values() for day in series if day < before})
    if len(days) < WATCHLIST_ATR_PERIOD:
        return None
    portfolio: list[Decimal] = []
    for day in days[-WATCHLIST_ATR_PERIOD:]:
        values = [series[day] for series in returns.values() if day in series]
        if values:
            portfolio.append(sum(values) / Decimal(len(values)))
    if not portfolio:
        return None
    return sum(abs(value) for value in portfolio) / Decimal(len(portfolio))
