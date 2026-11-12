"""交易标的：统一模型、上游分类映射与同步。

门面即出口：跨包只允许 `from app.instrument import ...`。
"""

from app.instrument.model import Instrument, InstrumentPair, spot_currency
from app.instrument.rules import TradingRules, trading_categories, trading_rules
from app.instrument.service import (
    DEFAULT_QUOTE_CURRENCY,
    SyncReport,
    get_instrument_pair,
    list_instruments,
    list_tradable,
    resolve_instrument,
    sync_instruments,
)

__all__ = [
    "DEFAULT_QUOTE_CURRENCY",
    "Instrument",
    "InstrumentPair",
    "SyncReport",
    "TradingRules",
    "get_instrument_pair",
    "list_instruments",
    "list_tradable",
    "resolve_instrument",
    "spot_currency",
    "sync_instruments",
    "trading_categories",
    "trading_rules",
]
