"""交易标的：统一模型、上游分类映射与同步。

门面即出口：跨包只允许 `from app.instrument import ...`。
"""

from app.instrument.model import Instrument, InstrumentPair
from app.instrument.rules import TradingRules, trading_rules
from app.instrument.service import (
    SyncReport,
    get_instrument_pair,
    list_instruments,
    list_tradable,
    resolve_instrument,
    sync_instruments,
)

__all__ = [
    "Instrument",
    "InstrumentPair",
    "SyncReport",
    "TradingRules",
    "get_instrument_pair",
    "list_instruments",
    "list_tradable",
    "resolve_instrument",
    "sync_instruments",
    "trading_rules",
]
