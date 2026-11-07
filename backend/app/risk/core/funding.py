"""资金费率与流动性监控（P2-06）。

只解析 OKX 公开接口的响应体并做阈值判断，不发网络请求；解析失败的样本
一律视为「不可用」，由调用方 fail-closed。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.risk.core.limits import ZERO, _exceeds


@dataclass(frozen=True, slots=True)
class FundingRateSample:
    inst_id: str
    funding_rate: Decimal
    next_funding_at: str | None


@dataclass(frozen=True, slots=True)
class BookSample:
    best_bid: Decimal
    best_ask: Decimal
    bid_depth: Decimal
    ask_depth: Decimal


@dataclass(frozen=True, slots=True)
class FundingObservation:
    inst_id: str
    funding_rate: Decimal
    next_funding_at: str | None
    best_bid: Decimal
    best_ask: Decimal
    bid_depth: Decimal
    ask_depth: Decimal


@dataclass(frozen=True, slots=True)
class FundingThresholds:
    max_abs_funding_rate: Decimal
    min_depth_notional: Decimal


@dataclass(frozen=True, slots=True)
class RiskSignal:
    kind: str
    severity: str
    action: str
    observed_value: Decimal
    threshold: Decimal
    inst_id: str
    payload: dict[str, Any]


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_funding(payload: dict[str, Any]) -> FundingRateSample | None:
    """解析 ``GET /api/v5/public/funding-rate`` 的响应体。"""
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    row = data[0]
    if not isinstance(row, dict):
        return None
    inst_id = row.get("instId")
    rate = _decimal(row.get("fundingRate"))
    if not isinstance(inst_id, str) or not inst_id or rate is None:
        return None
    next_funding = row.get("nextFundingTime")
    return FundingRateSample(
        inst_id=inst_id,
        funding_rate=rate,
        next_funding_at=str(next_funding) if next_funding is not None else None,
    )


def _side_depth(rows: Any) -> tuple[Decimal, Decimal] | None:
    """返回 (最优价, 名义深度)；空档位或非法价格视为不可用。"""
    if not isinstance(rows, list) or not rows:
        return None
    best: Decimal | None = None
    depth = ZERO
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            return None
        price = _decimal(row[0])
        size = _decimal(row[1])
        if price is None or size is None or price <= ZERO:
            return None
        if best is None:
            best = price
        depth += price * size
    if best is None:
        return None
    return best, depth


def parse_orderbook(payload: dict[str, Any]) -> BookSample | None:
    """解析 ``GET /api/v5/market/books`` 的响应体。"""
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    row = data[0]
    if not isinstance(row, dict):
        return None
    bids = _side_depth(row.get("bids"))
    asks = _side_depth(row.get("asks"))
    if bids is None or asks is None:
        return None
    return BookSample(
        best_bid=bids[0],
        best_ask=asks[0],
        bid_depth=bids[1],
        ask_depth=asks[1],
    )


def evaluate_market_health(
    observations: tuple[FundingObservation, ...], thresholds: FundingThresholds
) -> tuple[RiskSignal, ...]:
    """对每个标的产出资金费率与流动性信号。"""
    signals: list[RiskSignal] = []
    for observation in observations:
        absolute_rate = abs(observation.funding_rate)
        if _exceeds(absolute_rate, thresholds.max_abs_funding_rate):
            signals.append(
                RiskSignal(
                    kind="funding",
                    severity="tier1",
                    action="warn",
                    observed_value=absolute_rate,
                    threshold=thresholds.max_abs_funding_rate,
                    inst_id=observation.inst_id,
                    payload={
                        "funding_rate": str(observation.funding_rate),
                        "next_funding_at": observation.next_funding_at,
                    },
                )
            )
        min_depth = min(observation.bid_depth, observation.ask_depth)
        if min_depth < thresholds.min_depth_notional:
            signals.append(
                RiskSignal(
                    kind="liquidity",
                    severity="tier2",
                    action="warn",
                    observed_value=min_depth,
                    threshold=thresholds.min_depth_notional,
                    inst_id=observation.inst_id,
                    payload={
                        "bid_depth": str(observation.bid_depth),
                        "ask_depth": str(observation.ask_depth),
                        "best_bid": str(observation.best_bid),
                        "best_ask": str(observation.best_ask),
                    },
                )
            )
    return tuple(signals)


__all__ = [
    "BookSample",
    "FundingObservation",
    "FundingRateSample",
    "FundingThresholds",
    "RiskSignal",
    "evaluate_market_health",
    "parse_funding",
    "parse_orderbook",
]
