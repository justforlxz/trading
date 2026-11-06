"""OKX 行情快照：合约最新价与指数价。

指数价是 OKX 自行推导的参考价，**不等于**真实美股收盘价，只允许作为
`equity` 源不可用时的降级展示，并且必须带 `source=okx_index` 标注
（`docs/risk/external-dependencies.md` §2.9）。
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.adapters.okx.client import OkxClient

TICKER_PATH = "/api/v5/market/ticker"
INDEX_TICKERS_PATH = "/api/v5/market/index-tickers"


def _parse_price(item: dict[str, str], field: str) -> tuple[Decimal, datetime] | None:
    price = item.get(field)
    if not price:
        return None
    ts = item.get("ts")
    when = datetime.fromtimestamp(int(ts) / 1000, tz=UTC) if ts else datetime.now(tz=UTC)
    return Decimal(price), when


class OkxSnapshotSource:
    """读取合约最新价 / 指数价（只读公开端点）。"""

    def __init__(self, client: OkxClient) -> None:
        self._client = client

    async def fetch_last_price(self, inst_id: str) -> tuple[Decimal, datetime] | None:
        data = await self._client.get(TICKER_PATH, {"instId": inst_id}, limiter="ticker")
        if not data:
            return None
        return _parse_price(data[0], "last")
