"""显式「无行情源」实现：用于关闭外部依赖的运行环境。"""

from app.adapters.equity.base import EquitySourceUnavailable
from app.ports.market_data import EquityCandleRow, EquityQuote


class NullEquitySource:
    """始终报告不可用，让上层记录 `MISSING_SOURCE` 而不是编造数据。"""

    name = "none"

    async def aclose(self) -> None:
        return None

    async def fetch_daily(self, symbol: str, lookback_days: int = 10) -> list[EquityCandleRow]:
        raise EquitySourceUnavailable("equity source disabled (EQUITY_SOURCE=none)")

    async def fetch_quote(self, symbol: str) -> EquityQuote | None:
        raise EquitySourceUnavailable("equity source disabled (EQUITY_SOURCE=none)")
