"""首页汇总端点：一次返回八个模块，模块各自带状态与时刻。

路由只做 HTTP 映射：读取与降级都在 `app.dashboard` 里，指标、盈亏、风险与覆盖率
不在聚合层重算。任何模块不可用时响应仍是 200，`data` 为 `null`，`degraded` 里给出
简短原因。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter

from app.api.mapping import decimal_str
from app.api.schemas.correlation import MarketBreadth, MarketResonance
from app.api.schemas.dashboard import (
    DashboardAccountData,
    DashboardAccountModule,
    DashboardActivityItem,
    DashboardActivityModule,
    DashboardAlertItem,
    DashboardAlertsModule,
    DashboardDegradedItem,
    DashboardMarketData,
    DashboardMarketItem,
    DashboardMarketModule,
    DashboardPositionItem,
    DashboardPositionsData,
    DashboardPositionsModule,
    DashboardRecentBacktest,
    DashboardRiskData,
    DashboardRiskModule,
    DashboardStrategiesData,
    DashboardStrategiesModule,
    DashboardSummaryResponse,
    DashboardWatchlistData,
    DashboardWatchlistItem,
    DashboardWatchlistModule,
    DashboardWatchlistSummary,
)
from app.dashboard import (
    ActivityItem,
    AlertItem,
    DashboardSummary,
    MarketData,
    Module,
    PositionItem,
    PositionsData,
    RiskData,
    StrategiesData,
    WatchlistData,
    load_summary,
)
from app.instrument import display_symbol

__all__ = ["dashboard_router"]

dashboard_router = APIRouter(tags=["dashboard"])

# 契约的 DecimalString 只保证 12 位小数；广度比值与共振强度是浮点除法结果，
# 出接口前按与 `/api/market/overview` 相同的精度量化。
_VALUE_QUANTUM = Decimal("1e-12")


@dashboard_router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary() -> DashboardSummaryResponse:
    """首页一次请求返回八个模块；单个模块失败只把它自己标成不可用。"""

    summary = load_summary()
    return DashboardSummaryResponse(
        as_of=summary.as_of,
        market=_market(summary.market),
        account=_account(summary.account),
        risk=_risk(summary.risk),
        positions=_positions(summary.positions),
        watchlist=_watchlist(summary.watchlist),
        alerts=_alerts(summary.alerts),
        strategies=_strategies(summary.strategies),
        activity=_activity(summary.activity),
        degraded=_degraded(summary),
    )


def _optional(value: Decimal | None) -> str | None:
    """缺数据时给 `null`，不把 0 当成真实值写进响应。"""

    return None if value is None else decimal_str(value)


def _ratio_str(value: float | None) -> str | None:
    """浮点比值 → 契约里的定点字符串；没有数时如实给 `null`，不补 0。"""

    if value is None:
        return None
    return decimal_str(Decimal(str(value)).quantize(_VALUE_QUANTUM, rounding=ROUND_HALF_UP))


def _market(module: Module) -> DashboardMarketModule:
    data: MarketData | None = module.data
    return DashboardMarketModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=None
        if data is None
        else DashboardMarketData(
            session=data.session,
            items=[
                DashboardMarketItem(
                    inst_type=item.inst_type,
                    session=item.session,
                    primary_source=item.primary_source,
                    bar=item.bar,
                    as_of=item.as_of,
                    breadth=MarketBreadth(
                        advancers=item.advancers,
                        decliners=item.decliners,
                        unchanged=item.unchanged,
                        ratio=_ratio_str(item.breadth_ratio),
                        participants=item.participants,
                    ),
                    resonance=MarketResonance(
                        strength=_ratio_str(item.resonance_strength),
                        participants=item.resonance_participants,
                        window=item.resonance_window,
                    ),
                )
                for item in data.items
            ],
        ),
    )


def _account(module: Module) -> DashboardAccountModule:
    view = module.data
    return DashboardAccountModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=None
        if view is None
        else DashboardAccountData(
            account_id=view.account_id,
            currency=view.currency,
            equity=_optional(view.equity),
            available_equity=_optional(view.available_equity),
            cash_balance=_optional(view.cash_balance),
            unrealized_pnl=_optional(view.unrealized_pnl),
            used_margin=_optional(view.used_margin),
            available_margin=_optional(view.available_margin),
            margin_usage_pct=_optional(view.margin_usage_pct),
            day_pnl=_optional(view.day_pnl),
            captured_at=view.captured_at,
            source=view.source,
        ),
    )


def _risk(module: Module) -> DashboardRiskModule:
    data: RiskData | None = module.data
    if data is None:
        return DashboardRiskModule(status=module.status, as_of=module.as_of, error=module.error)
    summary = data.exposure.summary
    return DashboardRiskModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=DashboardRiskData(
            risk_level=summary.risk_level,
            currency=summary.currency,
            long_notional=decimal_str(summary.long_notional),
            short_notional=decimal_str(summary.short_notional),
            net_notional=decimal_str(summary.net_notional),
            gross_notional=decimal_str(summary.gross_notional),
            margin_usage_pct=_optional(summary.margin_usage_pct),
            margin_usage_basis=summary.margin_usage_basis,
            position_count=len(data.exposure.positions),
            near_stop_count=data.near_stop_count,
            high_leverage_count=data.high_leverage_count,
            missing_stop_count=data.missing_stop_count,
            max_single_instrument_weight_pct=_optional(data.max_single_instrument_weight_pct),
        ),
    )


def _positions(module: Module) -> DashboardPositionsModule:
    data: PositionsData | None = module.data
    return DashboardPositionsModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=None
        if data is None
        else DashboardPositionsData(
            total=data.total,
            exchange_count=data.exchange_count,
            manual_count=data.manual_count,
            exchange_status=data.exchange_status,
            items=[_position(item) for item in data.items],
        ),
    )


def _position(item: PositionItem) -> DashboardPositionItem:
    return DashboardPositionItem(
        position_ref=item.position_ref,
        source=item.source,
        inst_id=item.inst_id,
        display_symbol=item.display_symbol,
        side=item.side,
        leverage=_optional(item.leverage),
        mark_price=_optional(item.mark_price),
        notional=_optional(item.notional),
        stop_distance_pct=_optional(item.stop_distance_pct),
        unrealized_pnl=_optional(item.unrealized_pnl),
    )


def _watchlist(module: Module) -> DashboardWatchlistModule:
    data: WatchlistData | None = module.data
    if data is None:
        return DashboardWatchlistModule(
            status=module.status, as_of=module.as_of, error=module.error
        )
    return DashboardWatchlistModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=DashboardWatchlistData(
            summary=DashboardWatchlistSummary(
                total=data.summary.total,
                bullish=data.summary.bullish,
                bearish=data.summary.bearish,
                coverage_pct=decimal_str(data.summary.coverage_pct),
            ),
            items=[
                DashboardWatchlistItem(
                    inst_id=entry.instrument.symbol,
                    display_symbol=display_symbol(entry.instrument),
                    name=entry.instrument.product_key,
                    last_price=_optional(entry.quote.last_price),
                    change_pct_24h=_optional(entry.quote.change_pct_24h),
                    trend=entry.quote.trend,
                    rsi_14=_optional(entry.quote.rsi_14),
                    data_status=entry.quote.data_status,
                )
                for entry in data.entries
            ],
        ),
    )


def _alerts(module: Module) -> DashboardAlertsModule:
    items: tuple[AlertItem, ...] | None = module.data
    return DashboardAlertsModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=None if items is None else [_alert(item) for item in items],
    )


def _alert(item: AlertItem) -> DashboardAlertItem:
    return DashboardAlertItem(
        id=item.id,
        type=item.type,
        severity=item.severity,
        instrument_id=item.instrument_id,
        rule_id=item.rule_id,
        title=item.title,
        detail=item.detail,
        status=item.status,
        triggered_at=item.triggered_at,
    )


def _strategies(module: Module) -> DashboardStrategiesModule:
    data: StrategiesData | None = module.data
    if data is None:
        return DashboardStrategiesModule(
            status=module.status, as_of=module.as_of, error=module.error
        )
    run = data.recent_backtest
    return DashboardStrategiesModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=DashboardStrategiesData(
            total=data.summary.total,
            enabled=data.summary.enabled,
            running=data.summary.running,
            pending_signals=data.pending_signals,
            recent_backtest=None
            if run is None
            else DashboardRecentBacktest(
                run_id=run.run_id,
                data_source=run.data_source,
                window_days=(run.end_date - run.start_date).days,
                total_return=decimal_str(run.metrics["total_return"]),
                max_drawdown=decimal_str(run.metrics["max_drawdown"]),
                trade_count=int(run.metrics["trade_count"]),
                as_of=run.created_at,
            ),
        ),
    )


def _activity(module: Module) -> DashboardActivityModule:
    items: tuple[ActivityItem, ...] | None = module.data
    return DashboardActivityModule(
        status=module.status,
        as_of=module.as_of,
        error=module.error,
        data=None
        if items is None
        else [
            DashboardActivityItem(
                id=item.id,
                event_type=item.event_type,
                object_type=item.object_type,
                object_id=item.object_id,
                summary=item.summary,
                created_at=item.created_at,
            )
            for item in items
        ],
    )


def _degraded(summary: DashboardSummary) -> list[DashboardDegradedItem]:
    return [
        DashboardDegradedItem(
            module=name,
            status=module.status,
            reason=module.error or "模块不可用",
        )
        for name, module in summary.modules()
        if module.status != "ok"
    ]
