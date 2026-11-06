"""行情源装配：按配置选择实现，便于切换到付费源而不改业务代码。"""

import httpx

from app.adapters.equity.none import NullEquitySource
from app.adapters.equity.yahoo import YahooEquitySource
from app.ports.market_data import EquitySource


def build_equity_source(
    name: str,
    *,
    timeout_seconds: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EquitySource:
    """`yahoo`（默认）或 `none`；未知名字直接报错，避免静默降级。"""

    normalized = (name or "yahoo").strip().lower()
    if normalized == "yahoo":
        return YahooEquitySource(timeout_seconds, transport=transport)
    if normalized in {"none", "null", "off"}:
        return NullEquitySource()
    raise ValueError(f"unsupported equity source: {name!r}")
