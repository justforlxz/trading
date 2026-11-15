"""OKX 与手动持仓的合并视图：`position_ref` 与 `source` 的唯一口径。

`GET /api/positions` 与首页持仓模块共用这里的合并结果。只读库，不联网；名义价值、
止损价与止损距离直接采用 `app.risk` 的敞口输出，读取失败时这些可选列留空，不影响
持仓本身。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.positions import (
    DEFAULT_ACCOUNT_ID,
    ManualPositionView,
    exchange_positions,
    list_manual_positions,
)
from app.risk import RiskExposure, exposure_report

__all__ = ["MergedPosition", "MergedPositions", "load_merged_positions"]


@dataclass(frozen=True, slots=True)
class MergedPosition:
    """两种来源统一后的持仓行；来源专属字段在没有值时留空。"""

    position_ref: str
    source: str
    inst_id: str
    display_symbol: str
    name: str
    asset_class: str
    side: str
    size: Decimal
    avg_px: Decimal
    mark_px: Decimal | None
    upl: Decimal | None
    upl_ratio: Decimal | None
    lever: Decimal | None
    mgn_mode: str | None
    liq_px: Decimal | None
    margin: Decimal | None
    notional: Decimal | None
    stop_px: Decimal | None
    stop_distance_pct: Decimal | None
    price_status: str | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class MergedPositions:
    """合并结果：两种来源的条数、交易所同步状态与全部持仓行。"""

    as_of: datetime | None
    exchange_status: str
    exchange_count: int
    manual_count: int
    items: tuple[MergedPosition, ...]


def load_merged_positions() -> MergedPositions:
    """独立持仓接口：读取一次敞口，失败时可选列留空，持仓本身仍返回。"""

    try:
        exposure = exposure_report()
    except Exception:
        exposure = None
    return merge_positions(exposure)


def merge_positions(exposure: RiskExposure | None) -> MergedPositions:
    """用给定的敞口结果合并两种来源；`exposure=None` 时可选列留空。"""

    exchange = exchange_positions()
    manual = [item for item in list_manual_positions() if item.status == "open"]
    stops = _stop_prices(exposure)
    distances = _stop_distances(exposure)
    notionals = _notionals(exposure)

    rows: list[MergedPosition] = []
    for item in exchange.items:
        ref = f"exchange:{DEFAULT_ACCOUNT_ID}:{item.pos_id}"
        rows.append(
            MergedPosition(
                position_ref=ref,
                source="exchange",
                inst_id=item.inst_id,
                display_symbol=item.display_symbol,
                name=item.name,
                asset_class=item.asset_class,
                side=item.pos_side,
                size=item.size,
                avg_px=item.avg_px,
                mark_px=item.mark_px,
                upl=item.upl,
                upl_ratio=item.upl_ratio,
                lever=item.lever,
                mgn_mode=item.mgn_mode,
                liq_px=item.liq_px,
                margin=item.margin,
                notional=notionals.get(ref),
                stop_px=stops.get(ref),
                stop_distance_pct=distances.get(ref),
                price_status=None,
                updated_at=exchange.as_of,
            )
        )
    for item in manual:
        ref = f"manual:{item.id}"
        rows.append(
            MergedPosition(
                position_ref=ref,
                source="manual",
                inst_id=item.inst_id,
                display_symbol=item.display_symbol,
                name=item.name,
                asset_class=item.asset_class,
                side=item.side,
                size=item.quantity,
                avg_px=item.avg_cost,
                mark_px=item.price,
                upl=item.unrealized_pnl,
                upl_ratio=None,
                lever=item.leverage,
                mgn_mode=None,
                liq_px=None,
                margin=None,
                notional=_manual_notional(ref, item, notionals),
                stop_px=_manual_stop(ref, item, stops),
                stop_distance_pct=distances.get(ref),
                price_status=item.price_status,
                updated_at=item.updated_at,
            )
        )

    times = [exchange.as_of, *(item.updated_at for item in manual)]
    latest = max((time for time in times if time is not None), default=None)
    return MergedPositions(
        as_of=latest,
        exchange_status=exchange.status,
        exchange_count=len(exchange.items),
        manual_count=len(manual),
        items=tuple(rows),
    )


def _stop_prices(exposure: RiskExposure | None) -> dict[str, Decimal | None]:
    if exposure is None:
        return {}
    return {item.position_ref: item.stop_px for item in exposure.positions}


def _stop_distances(exposure: RiskExposure | None) -> dict[str, Decimal | None]:
    if exposure is None:
        return {}
    return {item.position_ref: item.stop_distance_pct for item in exposure.positions}


def _notionals(exposure: RiskExposure | None) -> dict[str, Decimal | None]:
    if exposure is None:
        return {}
    return {item.position_ref: item.notional for item in exposure.positions}


def _manual_notional(
    ref: str,
    item: ManualPositionView,
    notionals: dict[str, Decimal | None],
) -> Decimal | None:
    value = notionals.get(ref)
    return item.market_value if value is None else value


def _manual_stop(
    ref: str,
    item: ManualPositionView,
    stops: dict[str, Decimal | None],
) -> Decimal | None:
    value = stops.get(ref)
    return item.stop_px if value is None else value
