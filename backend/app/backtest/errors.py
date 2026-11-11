"""回测域错误。

回测里可预期的失败只有一类：输入本身不对。行情序列乱序、缺价，或者目标组合引用了
一个调用方没有提供标的静态信息的标的——这三种都能靠修输入解决，重试只会得到同一个
结果，因此在 API 边界都该报 400。

`BacktestError` 因此继承 `core.ValidationError` 而不是直接继承 `TradingError`：
`tests/contracts/test_port_contracts.py` 把 `TradingError` 的直接子类固定为六个，
域内新增错误只能挂在这六个语义之下（`app/exchange/errors.py` 同样这么做）。调用方
可以只捕获 `ValidationError`，需要精确区分时捕获本模块的具体类型。

代码写错了（例如把减仓单里的数量写成超过持仓）不属于业务失败，继续抛
`InvariantViolation`，由测试兜住。
"""

from __future__ import annotations

from app.core import ValidationError

__all__ = ["BacktestError", "BarSeriesError", "MissingInstrumentError"]


class BacktestError(ValidationError):
    """回测输入不合规的基类；都属于「改输入后可以重试」。"""


class BarSeriesError(BacktestError):
    """行情序列不合规：同一时刻重复、次序倒置，或持仓标的在该时刻没有可用价格。"""


class MissingInstrumentError(BacktestError):
    """目标组合引用了一个调用方没有提供标的静态信息的标的。"""
