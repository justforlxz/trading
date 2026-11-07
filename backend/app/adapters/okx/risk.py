"""OKX 公开行情中的资金费率与盘口深度来源（只读）。

只调用 ``/api/v5/public/funding-rate`` 与 ``/api/v5/market/books`` 两个公开
接口，不涉及任何账户或交易类调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.adapters.okx.client import OkxClient

FUNDING_RATE_PATH = "/api/v5/public/funding-rate"
BOOKS_PATH = "/api/v5/market/books"


@dataclass(frozen=True, slots=True)
class MarketHealthQuote:
    """一次观测到的资金费率与盘口原始响应。"""

    inst_id: str
    funding_payload: dict[str, Any]
    book_payload: dict[str, Any]


class OkxRiskMarketSource:
    """把两个公开端点包装成一次「观测」。"""

    def __init__(self, client: OkxClient, *, book_depth: int = 20) -> None:
        self._client = client
        self._book_depth = book_depth

    async def fetch_funding_rate(self, inst_id: str) -> dict[str, Any]:
        return await self._client.get(FUNDING_RATE_PATH, {"instId": inst_id}, limiter="ticker")

    async def fetch_book(self, inst_id: str) -> dict[str, Any]:
        return await self._client.get(
            BOOKS_PATH, {"instId": inst_id, "sz": str(self._book_depth)}, limiter="ticker"
        )

    async def observe(self, inst_id: str) -> MarketHealthQuote | None:
        """任一接口返回不可用时返回 ``None``，由调用方 fail-closed。"""
        try:
            funding = await self.fetch_funding_rate(inst_id)
            book = await self.fetch_book(inst_id)
        except Exception:  # 上游不可用统一降级为缺失
            return None
        return MarketHealthQuote(inst_id=inst_id, funding_payload=funding, book_payload=book)


__all__ = [
    "BOOKS_PATH",
    "FUNDING_RATE_PATH",
    "MarketHealthQuote",
    "OkxRiskMarketSource",
]
