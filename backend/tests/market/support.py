"""测试辅助：加载真实录制 fixture，构造假来源与落库对象。

fixture 均为 2026-11-06 从公开接口原样录制（见各文件 `_meta`），
离线用例只解析这些记录，不另行编造行情。
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.okx.candles import parse_candles
from app.market.models import Instrument
from app.ports.market_data import (
    CandleRow,
    EquityCandleRow,
    EquityQuote,
    InstrumentRow,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def fixture_instrument_rows() -> list[InstrumentRow]:
    from app.adapters.okx.instruments import to_instrument_row

    return [to_instrument_row(item) for item in load_fixture("instruments_swap.json")["data"]]


def fixture_candles(name: str = "okx_aapl_1h.json", bar: str = "1h") -> list[CandleRow]:
    data = load_fixture(name)["data"]
    return parse_candles(data, "AAPL-USDT-SWAP", bar, "okx_rest")


class FakeInstrumentSource:
    """固定返回给定 DTO 的标的来源（用于幂等与落库用例）。"""

    def __init__(self, rows: list[InstrumentRow]) -> None:
        self.rows = rows
        self.calls = 0

    async def fetch_instruments(self) -> list[InstrumentRow]:
        self.calls += 1
        return list(self.rows)


class FakeEquitySource:
    """可控的真实行情来源：要么给数据，要么抛不可用。"""

    name = "fake"

    def __init__(
        self,
        rows: list[EquityCandleRow] | None = None,
        quote: EquityQuote | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self.rows = rows or []
        self.quote = quote
        self.unavailable = unavailable

    async def fetch_daily(self, symbol: str, lookback_days: int = 10) -> list[EquityCandleRow]:
        if self.unavailable:
            from app.adapters.equity.base import EquitySourceUnavailable

            raise EquitySourceUnavailable("fixture: source unavailable")
        return list(self.rows)

    async def fetch_quote(self, symbol: str) -> EquityQuote | None:
        if self.unavailable:
            from app.adapters.equity.base import EquitySourceUnavailable

            raise EquitySourceUnavailable("fixture: source unavailable")
        return self.quote


def make_equity_rows(count: int = 5, start: datetime | None = None) -> list[EquityCandleRow]:
    """来自 `yahoo_chart_aapl.json` 的真实日线数量与收盘价（不新增虚构点）。"""

    payload = load_fixture("yahoo_chart_aapl.json")["chart"]["result"][0]
    timestamps = payload["timestamp"]
    closes = payload["indicators"]["quote"][0]["close"]
    rows: list[EquityCandleRow] = []
    for ts, close in list(zip(timestamps, closes, strict=True))[:count]:
        price = Decimal(str(close))
        rows.append(
            EquityCandleRow(
                symbol="AAPL",
                interval="1d",
                ts=datetime.fromtimestamp(int(ts), tz=UTC),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Decimal("0"),
                session="REGULAR",
                source="yahoo",
            )
        )
    return rows


def make_candle_rows(
    *,
    inst_id: str = "AAPL-USDT-SWAP",
    bar: str = "1h",
    start: datetime,
    count: int,
    price: str = "343.28",
    confirm_last: bool = False,
) -> list[CandleRow]:
    from app.market.core.bars import bar_seconds

    step = bar_seconds(bar)
    rows: list[CandleRow] = []
    for index in range(count):
        value = Decimal(price)
        rows.append(
            CandleRow(
                inst_id=inst_id,
                bar=bar,
                open_time=start.replace(microsecond=0) + timedelta(seconds=step * index),
                open=value,
                high=value,
                low=value,
                close=value,
                vol=Decimal("1"),
                vol_ccy=Decimal("1"),
                vol_ccy_quote=Decimal("1"),
                confirm=not (confirm_last and index == count - 1),
                source="okx_rest",
            )
        )
    return rows


async def insert_instrument(
    session: AsyncSession,
    inst_id: str = "AAPL-USDT-SWAP",
    *,
    asset_class: str = "us_equity",
    exchange: str | None = "XNAS",
) -> Instrument:
    """直接落一条标的（跳过网络，只为 K 线/覆盖率用例提供外键）。"""

    symbol = inst_id.split("-", 1)[0]
    instrument = Instrument(
        inst_id=inst_id,
        inst_family=inst_id,
        uly=symbol,
        inst_category=3,
        asset_class=asset_class,
        exchange=exchange,
        ct_val=Decimal("1"),
        ct_val_ccy=symbol,
        lot_sz=Decimal("0.01"),
        min_sz=Decimal("0.01"),
        tick_sz=Decimal("0.01"),
        lever=Decimal("20"),
        state="live",
        rule_type="normal",
        source_synced_at=datetime(2026, 11, 6, 13, 50, tzinfo=UTC),
        raw={},
    )
    session.add(instrument)
    await session.commit()
    await session.refresh(instrument)
    return instrument
