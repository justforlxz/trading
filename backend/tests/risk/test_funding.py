"""资金费率与流动性监控用例（P2-06）：录制 fixture、事件落库与 fail-closed。"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.adapters.okx.risk import MarketHealthQuote
from app.risk import service
from app.risk.core.funding import (
    FundingObservation,
    FundingThresholds,
    evaluate_market_health,
    parse_funding,
    parse_orderbook,
)
from app.risk.errors import RiskError
from app.risk.models import RiskEvent
from tests.risk.conftest import seed_strategy

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeSource:
    """按 instId 返回录制样本；未提供即模拟上游缺数据。"""

    def __init__(self, quotes: dict[str, MarketHealthQuote]) -> None:
        self.quotes = quotes
        self.calls: list[str] = []

    async def observe(self, inst_id: str) -> MarketHealthQuote | None:
        self.calls.append(inst_id)
        return self.quotes.get(inst_id)


def _quote(inst_id: str) -> MarketHealthQuote:
    funding = _load("funding_rate.json")
    funding["data"][0]["instId"] = inst_id
    return MarketHealthQuote(
        inst_id=inst_id, funding_payload=funding, book_payload=_load("books.json")
    )


def test_parse_funding_from_recorded_payload() -> None:
    sample = parse_funding(_load("funding_rate.json"))
    assert sample is not None
    assert sample.inst_id == "BTC-USDT-SWAP"
    assert sample.funding_rate == Decimal("0.0012")
    assert sample.next_funding_at == "1735689600000"


def test_parse_funding_rejects_empty_payload() -> None:
    assert parse_funding({"data": []}) is None
    assert parse_funding({}) is None
    assert parse_funding({"data": [{"instId": "X"}]}) is None


def test_parse_orderbook_computes_notional_depth() -> None:
    book = parse_orderbook(_load("books.json"))
    assert book is not None
    assert book.best_bid == Decimal("100.0")
    assert book.best_ask == Decimal("100.1")
    assert book.bid_depth == Decimal("999.5")
    assert book.ask_depth == Decimal("2003.0")


def test_parse_orderbook_rejects_missing_side() -> None:
    assert parse_orderbook({"data": [{"bids": [], "asks": [["1", "1"]]}]}) is None
    assert parse_orderbook({"data": []}) is None


def test_market_health_signals_for_funding_and_liquidity() -> None:
    observation = FundingObservation(
        inst_id="BTC-USDT-SWAP",
        funding_rate=Decimal("0.0012"),
        next_funding_at="1735689600000",
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        bid_depth=Decimal("999.5"),
        ask_depth=Decimal("2003.0"),
    )
    signals = evaluate_market_health(
        (observation,),
        FundingThresholds(
            max_abs_funding_rate=Decimal("0.0005"), min_depth_notional=Decimal("20000")
        ),
    )
    kinds = [signal.kind for signal in signals]
    assert kinds == ["funding", "liquidity"]
    assert signals[0].observed_value == Decimal("0.0012")
    assert signals[1].observed_value == Decimal("999.5")


def test_healthy_market_produces_no_signal() -> None:
    observation = FundingObservation(
        inst_id="BTC-USDT-SWAP",
        funding_rate=Decimal("0.0001"),
        next_funding_at=None,
        best_bid=Decimal("100"),
        best_ask=Decimal("100.1"),
        bid_depth=Decimal("600000"),
        ask_depth=Decimal("600000"),
    )
    assert (
        evaluate_market_health(
            (observation,),
            FundingThresholds(
                max_abs_funding_rate=Decimal("0.0005"), min_depth_notional=Decimal("20000")
            ),
        )
        == ()
    )


@pytest.mark.asyncio
async def test_observe_funding_records_one_event_per_signal(session) -> None:
    seeded = await seed_strategy(session)
    source = FakeSource({"BTC-USDT-SWAP": _quote("BTC-USDT-SWAP")})

    result = await service.observe_funding(
        session,
        source=source,
        strategy_id=seeded.strategy_id,
        inst_ids=("BTC-USDT-SWAP",),
        evaluation_key="2026-11-07",
    )

    assert [item["kind"] for item in result["breaches"]] == ["funding", "liquidity"]
    rows = (await session.execute(select(RiskEvent))).scalars().all()
    assert {row.kind for row in rows} == {"funding", "liquidity"}
    assert all(row.instrument_id == seeded.instrument_ids["BTC-USDT-SWAP"] for row in rows)


@pytest.mark.asyncio
async def test_observe_funding_is_idempotent(session) -> None:
    seeded = await seed_strategy(session)
    source = FakeSource({"BTC-USDT-SWAP": _quote("BTC-USDT-SWAP")})

    for _ in range(2):
        await service.observe_funding(
            session,
            source=source,
            strategy_id=seeded.strategy_id,
            inst_ids=("BTC-USDT-SWAP",),
            evaluation_key="2026-11-07",
        )

    rows = (await session.execute(select(RiskEvent))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_missing_market_data_is_fail_closed(session) -> None:
    seeded = await seed_strategy(session)
    source = FakeSource({})

    with pytest.raises(RiskError) as excinfo:
        await service.observe_funding(
            session,
            source=source,
            strategy_id=seeded.strategy_id,
            inst_ids=("BTC-USDT-SWAP",),
            evaluation_key="2026-11-07",
        )
    assert excinfo.value.code == "risk_market_data_unavailable"
    assert excinfo.value.status_code == 503
    assert excinfo.value.details["missing"] == ["BTC-USDT-SWAP"]
