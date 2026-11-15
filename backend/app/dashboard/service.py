"""首页汇总的读取编排：每个模块各读一次，单个模块失败只降级该模块。

本模块只做读取与组装，不写任何表，也不重新计算指标、盈亏、风险或覆盖率：

- 市场广度与共振来自 `app.market`；
- 账户与持仓来自 `app.positions`；
- 风险等级、规则结果与止损距离来自 `app.risk`；
- 自选摘要来自 `app.watchlist` 的 `summarize_entries`；
- 策略计数来自 `app.strategy` 的 `summarize_instances`；
- 最近回测来自 `app.backtest` 的 `latest_run`。

提醒读取 `alert_events` 的待处理行；活动读取 `activity_events` 的最近几条。
两者都由业务动作或提醒扫描写入，首页不在这里拼造文案，也不在读取时写库。

每个模块调用都在自己的异常边界里执行。异常只转成简短的公开原因，不把上游原始
响应或异常文本带进接口；一个模块失败不影响其他模块，接口仍返回 200。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from app.activity import list_activity
from app.alerts import list_alerts
from app.backtest import BacktestRunHeader, latest_run
from app.core import Clock, DataUnavailable, SystemClock, UpstreamError, ValidationError
from app.dashboard.positions import merge_positions
from app.market import asset_session, market_overview, primary_source
from app.positions import account_summary
from app.risk import (
    RULE_HIGH_LEVERAGE,
    RULE_STOP_DISTANCE,
    RULE_STOP_MISSING,
    RiskExposure,
    exposure_report,
)
from app.strategy import StrategySummary, summarize_instances
from app.watchlist import (
    WatchlistEntry,
    WatchlistSummary,
    list_entries,
    summarize_entries,
)

__all__ = [
    "MODULE_NAMES",
    "ActivityItem",
    "AlertItem",
    "DashboardSummary",
    "MarketData",
    "MarketItem",
    "Module",
    "PositionItem",
    "PositionsData",
    "RiskData",
    "StrategiesData",
    "WatchlistData",
    "load_summary",
]

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"
STATUS_UNCONFIGURED = "unconfigured"

MODULE_NAMES: tuple[str, ...] = (
    "market",
    "account",
    "risk",
    "positions",
    "watchlist",
    "alerts",
    "strategies",
    "activity",
)

INST_TYPES: tuple[str, ...] = ("SPOT", "SWAP")
MARKET_BAR = "1d"
TOP_ROWS = 5
ALERT_LIMIT = 5
RECENT_BACKTEST_DAYS = 30


@dataclass(frozen=True, slots=True)
class Module:
    """一个模块的读取结果；不可用时 `data` 为 `None`，不保留旧值。"""

    status: str
    as_of: datetime | None
    error: str | None
    data: Any


@dataclass(frozen=True, slots=True)
class MarketItem:
    """一个标的类别的市场状态、广度与共振。"""

    inst_type: str
    session: str
    primary_source: str
    bar: str
    as_of: datetime
    advancers: int
    decliners: int
    unchanged: int
    breadth_ratio: float | None
    participants: int
    resonance_strength: float | None
    resonance_participants: int
    resonance_window: int


@dataclass(frozen=True, slots=True)
class MarketData:
    """首页市场区：当前美股时段与两类标的的总览。"""

    session: str
    items: tuple[MarketItem, ...]


@dataclass(frozen=True, slots=True)
class RiskData:
    """风险卡：组合级数值与规则命中的计数。"""

    exposure: RiskExposure
    near_stop_count: int
    high_leverage_count: int
    missing_stop_count: int
    max_single_instrument_weight_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionItem:
    """首页持仓行；只给展示需要的字段，不返回完整持仓明细。"""

    position_ref: str
    source: str
    inst_id: str
    display_symbol: str
    side: str
    leverage: Decimal | None
    mark_price: Decimal | None
    notional: Decimal | None
    stop_distance_pct: Decimal | None
    unrealized_pnl: Decimal | None


@dataclass(frozen=True, slots=True)
class PositionsData:
    """持仓摘要：来源计数与最多五行持仓。"""

    total: int
    exchange_count: int
    manual_count: int
    exchange_status: str
    items: tuple[PositionItem, ...]


@dataclass(frozen=True, slots=True)
class WatchlistData:
    """自选摘要：计数、覆盖率与最多五行条目。"""

    summary: WatchlistSummary
    entries: tuple[WatchlistEntry, ...]


@dataclass(frozen=True, slots=True)
class AlertItem:
    """一条待处理提醒；来源是提醒事件表。"""

    id: str
    type: str
    severity: str | None
    instrument_id: str | None
    rule_id: str
    title: str
    detail: str
    status: str
    triggered_at: datetime


@dataclass(frozen=True, slots=True)
class StrategiesData:
    """策略卡：实例计数与最近 30 天的一次回测结果。"""

    summary: StrategySummary
    pending_signals: int | None
    recent_backtest: BacktestRunHeader | None


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """一条活动流水。"""

    id: str
    event_type: str
    object_type: str
    object_id: str
    summary: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    """八个模块各自的读取结果与整页时点。"""

    as_of: datetime
    market: Module
    account: Module
    risk: Module
    positions: Module
    watchlist: Module
    alerts: Module
    strategies: Module
    activity: Module

    def modules(self) -> tuple[tuple[str, Module], ...]:
        """按固定顺序返回模块，供接口生成 `degraded` 列表。"""

        return tuple((name, getattr(self, name)) for name in MODULE_NAMES)


def load_summary(*, clock: Clock | None = None) -> DashboardSummary:
    """读取八个模块；任何模块失败都在自己的边界内降级。"""

    moment = (clock or SystemClock()).now().astimezone(UTC).replace(microsecond=0)
    # 风险与持仓都要用敞口结果：一次请求只读一次，避免同一份数据被读两遍。
    # 敞口读取失败时把同一个异常交给两个模块，各自按自己的规则降级。
    exposure = _ExposureOnce()
    return DashboardSummary(
        as_of=moment,
        market=_isolate(lambda: _market(moment)),
        account=_isolate(_account),
        risk=_isolate(lambda: _risk(exposure)),
        positions=_isolate(lambda: _positions(exposure)),
        watchlist=_isolate(_watchlist),
        alerts=_isolate(_alerts),
        strategies=_isolate(lambda: _strategies(moment)),
        activity=_isolate(lambda: _activity(moment)),
    )


def _isolate(loader: Any) -> Module:
    try:
        return loader()
    except Exception as exc:  # 每个模块都必须独立降级
        return Module(status=STATUS_UNAVAILABLE, as_of=None, error=_reason(exc), data=None)


def _market(moment: datetime) -> Module:
    items = []
    for inst_type in INST_TYPES:
        session = asset_session("", moment, inst_type=inst_type)
        overview = market_overview(moment, MARKET_BAR, inst_type)
        items.append(
            MarketItem(
                inst_type=inst_type,
                session=session,
                primary_source=primary_source(session, "", inst_type),
                bar=overview.bar,
                as_of=overview.as_of,
                advancers=overview.breadth.advancers,
                decliners=overview.breadth.decliners,
                unchanged=overview.breadth.unchanged,
                breadth_ratio=overview.breadth.ratio,
                participants=overview.breadth.participants,
                resonance_strength=overview.resonance.strength,
                resonance_participants=overview.resonance.participants,
                resonance_window=overview.resonance.window,
            )
        )
    return Module(
        status=STATUS_OK,
        as_of=moment,
        error=None,
        data=MarketData(session=asset_session("tokenized_equity", moment), items=tuple(items)),
    )


def _account() -> Module:
    view = account_summary()
    if view.status == STATUS_UNCONFIGURED:
        return Module(
            status=STATUS_UNCONFIGURED,
            as_of=view.captured_at,
            error="账户未配置",
            data=None,
        )
    return Module(status=view.status, as_of=view.captured_at, error=None, data=view)


class _ExposureOnce:
    """一次请求内只读一次敞口；读到异常也缓存，供后续模块按自己的规则降级。"""

    def __init__(self) -> None:
        self._loaded = False
        self._value: RiskExposure | None = None
        self._error: Exception | None = None

    def get(self) -> RiskExposure:
        if not self._loaded:
            self._loaded = True
            try:
                self._value = exposure_report()
            except Exception as exc:  # 缓存后原样抛给每个调用方
                self._error = exc
        if self._error is not None:
            raise self._error
        # 读取成功时 `_value` 一定已赋值；读取失败的分支已在上方抛出。
        return cast("RiskExposure", self._value)


def _risk(exposure_once: _ExposureOnce) -> Module:
    exposure = exposure_once.get()
    near_stop = {
        rule.position_ref
        for rule in exposure.rules
        if rule.rule_id == RULE_STOP_DISTANCE and rule.position_ref is not None
    }
    high_leverage = {
        rule.position_ref
        for rule in exposure.rules
        if rule.rule_id == RULE_HIGH_LEVERAGE and rule.position_ref is not None
    }
    missing_stop = {
        rule.position_ref
        for rule in exposure.rules
        if rule.rule_id == RULE_STOP_MISSING and rule.position_ref is not None
    }
    weights = [item.weight_pct for item in exposure.positions if item.weight_pct is not None]
    return Module(
        status=STATUS_OK,
        as_of=exposure.as_of,
        error=None,
        data=RiskData(
            exposure=exposure,
            near_stop_count=len(near_stop),
            high_leverage_count=len(high_leverage),
            missing_stop_count=len(missing_stop),
            max_single_instrument_weight_pct=max(weights) if weights else None,
        ),
    )


def _positions(exposure_once: _ExposureOnce) -> Module:
    # 止损距离与名义价值只在 B3 的敞口结果里，本模块只借用它的输出；敞口读取失败
    # 时这两列留空，持仓本身仍然返回，不能因为风险模块失败而把持仓一并判成不可用。
    snapshot = merge_positions(_optional_exposure(exposure_once))
    items = tuple(
        PositionItem(
            position_ref=item.position_ref,
            source=item.source,
            inst_id=item.inst_id,
            display_symbol=item.display_symbol,
            side=item.side,
            leverage=item.lever,
            mark_price=item.mark_px,
            notional=item.notional,
            stop_distance_pct=item.stop_distance_pct,
            unrealized_pnl=item.upl,
        )
        for item in snapshot.items[:TOP_ROWS]
    )
    return Module(
        status=STATUS_OK,
        as_of=snapshot.as_of,
        error=None,
        data=PositionsData(
            total=len(snapshot.items),
            exchange_count=snapshot.exchange_count,
            manual_count=snapshot.manual_count,
            exchange_status=snapshot.exchange_status,
            items=items,
        ),
    )


def _optional_exposure(exposure_once: _ExposureOnce) -> RiskExposure | None:
    """敞口只是持仓摘要的可选补充；读取失败时不影响持仓本身。"""

    try:
        return exposure_once.get()
    except Exception:
        return None


def _watchlist() -> Module:
    entries = list_entries()
    summary = summarize_entries(entries)
    last_updated = max(
        (entry.quote.last_candle_at for entry in entries if entry.quote.last_candle_at is not None),
        default=None,
    )
    return Module(
        status=STATUS_OK,
        as_of=last_updated,
        error=None,
        data=WatchlistData(summary=summary, entries=tuple(entries[:TOP_ROWS])),
    )


def _alerts() -> Module:
    records, _ = list_alerts(status="pending", limit=ALERT_LIMIT)
    items = tuple(
        AlertItem(
            id=record.id,
            type=record.type,
            severity=record.severity,
            instrument_id=record.instrument_id,
            rule_id=record.rule_id,
            title=record.title,
            detail=record.detail,
            status=record.status,
            triggered_at=record.triggered_at,
        )
        for record in records
    )
    return Module(
        status=STATUS_OK,
        as_of=None if not items else items[0].triggered_at,
        error=None,
        data=items,
    )


def _strategies(moment: datetime) -> Module:
    since = moment - timedelta(days=RECENT_BACKTEST_DAYS)
    return Module(
        status=STATUS_OK,
        as_of=moment,
        error=None,
        data=StrategiesData(
            summary=summarize_instances(),
            # 待确认信号的事件表由 B6/B8 交付；现在没有可核对的事实，返回 `None`
            # 比写 0 更诚实，界面可以显示「未接入」。
            pending_signals=None,
            recent_backtest=latest_run(created_since=since),
        ),
    )


def _activity(moment: datetime) -> Module:
    records, _ = list_activity(limit=ALERT_LIMIT)
    items = tuple(
        ActivityItem(
            id=record.id,
            event_type=record.event_type,
            object_type=record.object_type,
            object_id=record.object_id,
            summary=record.summary,
            created_at=record.created_at,
        )
        for record in records
    )
    return Module(
        status=STATUS_OK,
        as_of=items[0].created_at if items else moment,
        error=None,
        data=items,
    )


def _reason(exc: Exception) -> str:
    """异常 → 简短公开原因；不带异常文本，避免泄露上游响应。"""

    if isinstance(exc, UpstreamError):
        return "上游数据源不可用"
    if isinstance(exc, DataUnavailable):
        return "数据暂不可用"
    if isinstance(exc, ValidationError):
        return "数据校验失败"
    return "数据读取失败"
