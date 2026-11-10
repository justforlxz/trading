"""市场域：K 线对齐、缺口检测与相关性计算。

本节点只提供纯函数，采集与落库在后续节点接入。跨包调用一律走本门面，
不允许 `from app.market.candles import ...` 之类的子模块直连。
"""

from app.market.candles import (
    duplicate_open_times,
    expected_open_times,
    find_gaps,
    floor_open_time,
    out_of_order,
)
from app.market.correlation import (
    MIN_SAMPLES,
    correlate,
    lagged_correlation,
    p_value,
    pearson,
    rolling_sign_agreement,
    spearman,
)

__all__ = [
    "MIN_SAMPLES",
    "correlate",
    "duplicate_open_times",
    "expected_open_times",
    "find_gaps",
    "floor_open_time",
    "lagged_correlation",
    "out_of_order",
    "p_value",
    "pearson",
    "rolling_sign_agreement",
    "spearman",
]
