"""八个内置指标的计算本体。

全部是纯函数：只读入参、只返回新对象，不碰 IO，也不在模块里留可变的中间状态。
`app.indicators.compute` 负责参数校验与「K 线不足则返回空序列」，这里的函数假定
入参已经过校验、且 K 线数量满足各自的热身长度。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.core import Bar, ValidationError
from app.indicators.registry import register_indicator
from app.indicators.types import IndicatorDefinition, Param, ParamValue, Point, Series

_ZERO = Decimal(0)
_ONE = Decimal(1)
_TWO = Decimal(2)
_THREE = Decimal(3)
_HUNDRED = Decimal(100)


def _assemble(
    name: str,
    params: Mapping[str, ParamValue],
    bars: Sequence[Bar],
    outputs: Sequence[str],
    *columns: Sequence[Decimal | None],
) -> Series:
    """把若干列按 K 线顺序拼成序列；每列长度必须与 K 线数量一致。"""

    points = tuple(
        Point(time=bar.open_time, values=dict(zip(outputs, values, strict=True)))
        for bar, values in zip(bars, zip(*columns, strict=True), strict=True)
    )
    return Series(name=name, params=dict(params), points=points)


def _known(value: Decimal | None) -> Decimal:
    """取窗口已成形位置上的值；未定义的位置不会走到这里。"""

    assert value is not None
    return value


def _rolling_mean(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """定长窗口均值，前 `period - 1` 个位置为 `None`。"""

    window = sum(values[:period])
    column: list[Decimal | None] = [None] * (period - 1)
    column.append(window / Decimal(period))
    for index in range(period, len(values)):
        window += values[index] - values[index - period]
        column.append(window / Decimal(period))
    return column


def _exponential_mean(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """指数移动平均：首值取前 `period` 个的算术平均，之后按 `2/(n+1)` 的权重递推。"""

    alpha = _TWO / Decimal(period + 1)
    previous = sum(values[:period]) / Decimal(period)
    column: list[Decimal | None] = [None] * (period - 1)
    column.append(previous)
    for value in values[period:]:
        previous = alpha * value + (_ONE - alpha) * previous
        column.append(previous)
    return column


def sma(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """简单移动平均：最近 N 根收盘价的算术平均。"""

    period = int(params["period"])
    return _assemble(
        "sma", params, bars, ("sma",), _rolling_mean([bar.close for bar in bars], period)
    )


def ema(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """指数移动平均：首值取前 N 根收盘价的算术平均，之后按权重递推。"""

    period = int(params["period"])
    return _assemble(
        "ema", params, bars, ("ema",), _exponential_mean([bar.close for bar in bars], period)
    )


def _rsi_value(avg_gain: Decimal, avg_loss: Decimal) -> Decimal | None:
    """RSI 的取值：无下跌时顶在 100，涨跌都没有（全平）时无方向返回 `None`。"""

    if avg_loss == 0:
        return None if avg_gain == 0 else _HUNDRED
    return _HUNDRED - _HUNDRED / (_ONE + avg_gain / avg_loss)


def rsi(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """相对强弱指标：涨跌幅的 Wilder 平滑。"""

    period = int(params["period"])
    closes = [bar.close for bar in bars]
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for index in range(1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gains.append(max(delta, _ZERO))
        losses.append(max(-delta, _ZERO))
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)
    column: list[Decimal | None] = [None] * period
    column.append(_rsi_value(avg_gain, avg_loss))
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + gain) / Decimal(period)
        avg_loss = (avg_loss * (period - 1) + loss) / Decimal(period)
        column.append(_rsi_value(avg_gain, avg_loss))
    return _assemble("rsi", params, bars, ("rsi",), column)


def macd(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """指数平滑异同移动平均：快慢线之差、其信号线与柱状差。"""

    fast = int(params["fast"])
    slow = int(params["slow"])
    signal = int(params["signal"])
    closes = [bar.close for bar in bars]
    fast_line = _exponential_mean(closes, fast)
    slow_line = _exponential_mean(closes, slow)
    offset = slow - 1
    macd_values = [
        _known(fast_line[index]) - _known(slow_line[index]) for index in range(offset, len(closes))
    ]
    signal_values = _exponential_mean(macd_values, signal)
    histogram = [
        None if value is None else difference - value
        for difference, value in zip(macd_values, signal_values, strict=True)
    ]
    pad: list[Decimal | None] = [None] * offset
    return _assemble(
        "macd",
        params,
        bars,
        ("macd", "signal", "hist"),
        pad + macd_values,
        pad + signal_values,
        pad + histogram,
    )


def atr(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """平均真实波幅：真实波幅首值取当根高低差，之后取 Wilder 平滑。"""

    period = int(params["period"])
    ranges: list[Decimal] = [bars[0].high - bars[0].low]
    for index in range(1, len(bars)):
        current = bars[index]
        previous = bars[index - 1]
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    average = sum(ranges[:period]) / Decimal(period)
    column: list[Decimal | None] = [None] * (period - 1)
    column.append(average)
    for value in ranges[period:]:
        average = (average * (period - 1) + value) / Decimal(period)
        column.append(average)
    return _assemble("atr", params, bars, ("atr",), column)


def bollinger(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """布林带：移动平均为中轨，上下轨是中轨加减 N 倍总体标准差。"""

    period = int(params["period"])
    width = Decimal(str(params["num_std"]))
    closes = [bar.close for bar in bars]
    middle = _rolling_mean(closes, period)
    upper: list[Decimal | None] = []
    lower: list[Decimal | None] = []
    for index in range(period - 1, len(closes)):
        center = _known(middle[index])
        window = closes[index - period + 1 : index + 1]
        variance = sum((value - center) ** 2 for value in window) / Decimal(period)
        spread = variance.sqrt() * width
        upper.append(center + spread)
        lower.append(center - spread)
    pad: list[Decimal | None] = [None] * (period - 1)
    return _assemble(
        "bollinger", params, bars, ("upper", "middle", "lower"), pad + upper, middle, pad + lower
    )


def vwap(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """成交量加权均价：窗口内典型价的成交量加权平均，窗口零成交量时该点为 `None`。"""

    period = int(params["period"])
    typical = [(bar.high + bar.low + bar.close) / _THREE for bar in bars]
    volumes = [bar.volume for bar in bars]
    column: list[Decimal | None] = [None] * (period - 1)
    for index in range(period - 1, len(bars)):
        start = index - period + 1
        total = sum(volumes[start : index + 1])
        if total == 0:
            column.append(None)
            continue
        weighted = sum(
            typical[position] * volumes[position] for position in range(start, index + 1)
        )
        column.append(weighted / total)
    return _assemble("vwap", params, bars, ("vwap",), column)


def volume_ma(bars: Sequence[Bar], params: Mapping[str, ParamValue]) -> Series:
    """成交量移动平均：最近 N 根成交量的算术平均。"""

    period = int(params["period"])
    return _assemble(
        "volume_ma",
        params,
        bars,
        ("volume_ma",),
        _rolling_mean([bar.volume for bar in bars], period),
    )


def _period_warmup(params: Mapping[str, ParamValue]) -> int:
    return int(params["period"])


def _rsi_warmup(params: Mapping[str, ParamValue]) -> int:
    return int(params["period"]) + 1


def _macd_warmup(params: Mapping[str, ParamValue]) -> int:
    return int(params["slow"]) + int(params["signal"]) - 1


def _macd_check(params: Mapping[str, ParamValue]) -> None:
    if int(params["fast"]) >= int(params["slow"]):
        raise ValidationError("macd 的 fast 必须小于 slow")


register_indicator(
    IndicatorDefinition(
        name="sma",
        title="简单移动平均",
        summary="收盘价在最近 N 根 K 线上的算术平均。",
        inputs=("close",),
        outputs=("sma",),
        params=(Param("period", "周期", "int", 20, 1, 500),),
        min_length=20,
    ),
    warmup=_period_warmup,
    compute=sma,
)

register_indicator(
    IndicatorDefinition(
        name="ema",
        title="指数移动平均",
        summary="收盘价的指数移动平均, 首值取前 N 根的算术平均。",
        inputs=("close",),
        outputs=("ema",),
        params=(Param("period", "周期", "int", 20, 1, 500),),
        min_length=20,
    ),
    warmup=_period_warmup,
    compute=ema,
)

register_indicator(
    IndicatorDefinition(
        name="rsi",
        title="相对强弱指标",
        summary="涨跌幅的 Wilder 平滑, 全平序列无方向。",
        inputs=("close",),
        outputs=("rsi",),
        params=(Param("period", "周期", "int", 14, 1, 500),),
        min_length=15,
    ),
    warmup=_rsi_warmup,
    compute=rsi,
)

register_indicator(
    IndicatorDefinition(
        name="macd",
        title="指数平滑异同移动平均",
        summary="快慢指数均线之差, 及其信号线与柱状差。",
        inputs=("close",),
        outputs=("macd", "signal", "hist"),
        params=(
            Param("fast", "快线周期", "int", 12, 1, 500),
            Param("slow", "慢线周期", "int", 26, 1, 500),
            Param("signal", "信号线周期", "int", 9, 1, 500),
        ),
        min_length=34,
    ),
    warmup=_macd_warmup,
    compute=macd,
    check=_macd_check,
)

register_indicator(
    IndicatorDefinition(
        name="atr",
        title="平均真实波幅",
        summary="真实波幅的 Wilder 平均。",
        inputs=("high", "low", "close"),
        outputs=("atr",),
        params=(Param("period", "周期", "int", 14, 1, 500),),
        min_length=14,
    ),
    warmup=_period_warmup,
    compute=atr,
)

register_indicator(
    IndicatorDefinition(
        name="bollinger",
        title="布林带",
        summary="移动平均中轨, 上下轨为中轨加减 N 倍标准差。",
        inputs=("close",),
        outputs=("upper", "middle", "lower"),
        params=(
            Param("period", "周期", "int", 20, 1, 500),
            Param("num_std", "标准差倍数", "float", 2.0, 0.1, 10.0),
        ),
        min_length=20,
    ),
    warmup=_period_warmup,
    compute=bollinger,
)

register_indicator(
    IndicatorDefinition(
        name="vwap",
        title="成交量加权均价",
        summary="窗口内典型价的成交量加权平均。",
        inputs=("high", "low", "close", "volume"),
        outputs=("vwap",),
        params=(Param("period", "周期", "int", 20, 1, 500),),
        min_length=20,
    ),
    warmup=_period_warmup,
    compute=vwap,
)

register_indicator(
    IndicatorDefinition(
        name="volume_ma",
        title="成交量移动平均",
        summary="成交量的算术移动平均。",
        inputs=("volume",),
        outputs=("volume_ma",),
        params=(Param("period", "周期", "int", 20, 1, 500),),
        min_length=20,
    ),
    warmup=_period_warmup,
    compute=volume_ma,
)
