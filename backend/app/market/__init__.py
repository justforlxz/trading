"""市场域：历史 K 线的下载/落库/完整性、交易时段与来源治理、相关性与关系矩阵。

本域对外发布三类东西：
- 纯函数（对齐、缺口、重复、相关系数、时段、跨源偏离）—— 输入输出可直接断言；
- 编排入口（同步、读取、完整性报告、两标的相关性、相关矩阵与快照、市场总览、当前
  有效行情）—— 负责 IO 与事务边界；
- 时段与来源的词表（`SESSION_*` / `EXCHANGE_*` / 资产类别），供上层查表与落库。

跨包调用一律走本门面，不允许 `from app.market.candles import ...` 之类的子模块直连。
注意 `correlation(...)` 是「两个标的」的编排入口，纯数学模块仍是 `app.market.correlation`。
"""

from app.market.breadth import (
    MIN_RESONANCE_PARTICIPANTS,
    advance_decline,
    resonance_strength,
)
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
from app.market.divergence import DEFAULT_THRESHOLD_PCT, DivergenceAlert, Quote, divergence
from app.market.funding import (
    FundingPoint,
    backfill_funding,
    load_funding,
    parse_funding_rows,
    upsert_funding,
)
from app.market.matrix import Matrix, build_matrix, correlation_matrix
from app.market.model import Candle, CorrelationSnapshot
from app.market.rolling import relative_strength_ratio, rolling_correlation
from app.market.service import (
    correlation,
    current_bar,
    integrity,
    load_snapshot,
    market_overview,
    save_snapshot,
)
from app.market.session import (
    COMMODITY_TOKEN,
    CRYPTO,
    EXCHANGE_CLOSED,
    EXCHANGE_OPEN,
    SESSION_CLOSED,
    SESSION_POST,
    SESSION_PRE,
    SESSION_REGULAR,
    TOKENIZED_EQUITY,
    UNKNOWN_ASSET,
    asset_session,
    daily_open_time,
    exchange_session,
    is_trading_day,
    primary_source,
)
from app.market.sync import data_range, load_candles, sync_candles, upsert_candles

__all__ = [
    "COMMODITY_TOKEN",
    "CRYPTO",
    "DEFAULT_THRESHOLD_PCT",
    "EXCHANGE_CLOSED",
    "EXCHANGE_OPEN",
    "MIN_RESONANCE_PARTICIPANTS",
    "MIN_SAMPLES",
    "SESSION_CLOSED",
    "SESSION_POST",
    "SESSION_PRE",
    "SESSION_REGULAR",
    "TOKENIZED_EQUITY",
    "UNKNOWN_ASSET",
    "Candle",
    "CorrelationSnapshot",
    "DivergenceAlert",
    "FundingPoint",
    "Matrix",
    "Quote",
    "advance_decline",
    "asset_session",
    "backfill_funding",
    "build_matrix",
    "correlate",
    "correlation",
    "correlation_matrix",
    "current_bar",
    "daily_open_time",
    "data_range",
    "divergence",
    "duplicate_open_times",
    "exchange_session",
    "expected_open_times",
    "find_gaps",
    "floor_open_time",
    "integrity",
    "is_trading_day",
    "lagged_correlation",
    "load_candles",
    "load_funding",
    "load_snapshot",
    "market_overview",
    "out_of_order",
    "p_value",
    "parse_funding_rows",
    "pearson",
    "primary_source",
    "relative_strength_ratio",
    "resonance_strength",
    "rolling_correlation",
    "rolling_sign_agreement",
    "save_snapshot",
    "spearman",
    "sync_candles",
    "upsert_candles",
    "upsert_funding",
]
