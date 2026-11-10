"""市场域：历史 K 线与资金费的下载/落库/完整性，以及相关性计算。

本域对外只发布两件事：
- 纯函数（对齐、缺口、重复、相关系数）—— 输入输出可直接断言；
- 编排入口（同步、读取、完整性报告、两标的相关性）—— 负责 IO 与事务边界。

跨包调用一律走本门面，不允许 `from app.market.candles import ...` 之类的子模块直连。
注意 `correlation(...)` 是「两个标的」的编排入口，纯数学模块仍是 `app.market.correlation`。
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
from app.market.funding import (
    FundingPoint,
    backfill_funding,
    load_funding,
    parse_funding_rows,
    upsert_funding,
)
from app.market.model import Candle
from app.market.service import correlation, integrity
from app.market.sync import data_range, load_candles, sync_candles, upsert_candles

__all__ = [
    "MIN_SAMPLES",
    "Candle",
    "FundingPoint",
    "backfill_funding",
    "correlate",
    "correlation",
    "data_range",
    "duplicate_open_times",
    "expected_open_times",
    "find_gaps",
    "floor_open_time",
    "integrity",
    "lagged_correlation",
    "load_candles",
    "load_funding",
    "out_of_order",
    "p_value",
    "parse_funding_rows",
    "pearson",
    "rolling_sign_agreement",
    "spearman",
    "sync_candles",
    "upsert_candles",
    "upsert_funding",
]
