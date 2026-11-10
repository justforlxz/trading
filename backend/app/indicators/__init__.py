"""技术指标：纯函数实现，回测与实时共用同一份计算。

八种内置指标（SMA / EMA / RSI / MACD / ATR / 布林带 / VWAP / 成交量均线）在导入
本包时登记；调用方只经 `compute(name, bars, params)` 取结果，不关心实现落在哪个
模块。指标都是纯函数：不碰 IO，不写缓存，同一组入参重复调用结果相等。

跨包调用一律走本门面，不允许 `from app.indicators.registry import ...` 之类的子
模块直连。
"""

import app.indicators.indicators  # noqa: F401  # 导入即登记内置指标
from app.indicators.registry import compute, definition, list_definitions
from app.indicators.types import IndicatorDefinition, Param, ParamValue, Point, Series

__all__ = [
    "IndicatorDefinition",
    "Param",
    "ParamValue",
    "Point",
    "Series",
    "compute",
    "definition",
    "list_definitions",
]
