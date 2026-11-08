"""风控编排：取数、调用纯函数、把判决落成幂等事件。

所有计算都在 ``app.risk.core`` 中完成。本模块的职责是：缺失依赖时 fail-closed
（拒绝放行而不是放行），把判决写成可审计事件，并把结果整理成字段稳定、同参数
重复执行逐字段一致的字典。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.risk import data
from app.risk.core import drawdown, funding, limits, portfolio
from app.risk.core.drawdown import DrawdownThresholds
from app.risk.core.funding import FundingObservation, FundingThresholds
from app.risk.core.limits import Breach, LegIntent, Limits
from app.risk.errors import RiskError
from app.risk.models import RiskEvent, RiskPolicy

ZERO = Decimal("0")

THRESHOLD_FIELDS = (
    "max_order_notional",
    "max_leg_weight",
    "max_leverage",
    "max_gross_exposure",
    "max_net_exposure",
    "max_instrument_weight",
    "max_concentration",
    "drawdown_warn",
    "drawdown_reduce",
    "drawdown_close",
    "funding_rate_threshold",
    "min_depth_notional",
)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# 阈值
# ---------------------------------------------------------------------------


def thresholds_from_settings(settings: Settings) -> dict[str, Decimal]:
    return {
        "max_order_notional": _decimal(settings.risk_max_order_notional),
        "max_leg_weight": _decimal(settings.risk_max_leg_weight),
        "max_leverage": _decimal(settings.risk_max_leverage),
        "max_gross_exposure": _decimal(settings.risk_max_gross_exposure),
        "max_net_exposure": _decimal(settings.risk_max_net_exposure),
        "max_instrument_weight": _decimal(settings.risk_max_instrument_weight),
        "max_concentration": _decimal(settings.risk_max_concentration),
        "drawdown_warn": _decimal(settings.risk_drawdown_warn),
        "drawdown_reduce": _decimal(settings.risk_drawdown_reduce),
        "drawdown_close": _decimal(settings.risk_drawdown_close),
        "funding_rate_threshold": _decimal(settings.risk_funding_rate_threshold),
        "min_depth_notional": _decimal(settings.risk_min_depth_notional),
    }


def validate_thresholds(values: dict[str, Decimal]) -> None:
    """校验一组阈值；非法时抛 ``risk_invalid_threshold``（422）。"""
    missing = [field for field in THRESHOLD_FIELDS if field not in values]
    if missing:
        raise RiskError(
            "risk_invalid_threshold",
            "缺少风控阈值字段",
            details={"missing": missing},
        )
    for field in THRESHOLD_FIELDS:
        if values[field] <= ZERO:
            raise RiskError(
                "risk_invalid_threshold",
                f"风控阈值必须为正数: {field}",
                details={"field": field, "value": _text(values[field])},
            )
    drawdown.validate_thresholds(
        DrawdownThresholds(
            warn=values["drawdown_warn"],
            reduce=values["drawdown_reduce"],
            close=values["drawdown_close"],
        )
    )


def policy_thresholds(policy: RiskPolicy) -> dict[str, Decimal]:
    return {field: _decimal(getattr(policy, field)) for field in THRESHOLD_FIELDS}


def _policy_view(policy: RiskPolicy) -> dict[str, Any]:
    return {
        "scope": policy.scope,
        "strategy_id": policy.strategy_id,
        "version": policy.version,
        "thresholds": {
            field: _text(policy_thresholds(policy)[field]) for field in THRESHOLD_FIELDS
        },
        "updated_at": _iso(policy.updated_at),
        "updated_by": policy.updated_by,
        "note": policy.note,
    }


def policy_view(policy: RiskPolicy, *, source: str = "stored") -> dict[str, Any]:
    """阈值策略的响应视图（阈值以字符串返回，避免 float 误差）。

    `source="defaults"` 表示这是一份**未落库**的缺省阈值, 因此没有版本号。
    """

    view = _policy_view(policy)
    view["policy_source"] = source
    if source == "defaults":
        view["version"] = None
    return view


def _limits_from(values: dict[str, Decimal]) -> Limits:
    return Limits(
        max_order_notional=values["max_order_notional"],
        max_leg_weight=values["max_leg_weight"],
        max_leverage=values["max_leverage"],
        max_gross_exposure=values["max_gross_exposure"],
        max_net_exposure=values["max_net_exposure"],
        max_instrument_weight=values["max_instrument_weight"],
        max_concentration=values["max_concentration"],
    )


# ---------------------------------------------------------------------------
# 阈值策略
# ---------------------------------------------------------------------------


async def get_policy(
    session: AsyncSession, *, scope: str = "global", strategy_id: int | None = None
) -> RiskPolicy | None:
    stmt = select(RiskPolicy).where(RiskPolicy.scope == scope)
    if strategy_id is None:
        stmt = stmt.where(RiskPolicy.strategy_id.is_(None))
    else:
        stmt = stmt.where(RiskPolicy.strategy_id == strategy_id)
    stmt = stmt.order_by(RiskPolicy.version.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_create_policy(
    session: AsyncSession, *, scope: str = "global", strategy_id: int | None = None
) -> RiskPolicy:
    """读取最新阈值策略；不存在时用配置默认值建 v1（幂等）。"""
    existing = await get_policy(session, scope=scope, strategy_id=strategy_id)
    if existing is not None:
        return existing

    policy = RiskPolicy(
        scope=scope,
        strategy_id=strategy_id,
        version=1,
        updated_by="system:defaults",
        note="初始化默认阈值",
        **thresholds_from_settings(get_settings()),
    )
    session.add(policy)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent = await get_policy(session, scope=scope, strategy_id=strategy_id)
        if concurrent is None:
            raise
        return concurrent
    await session.refresh(policy)
    return policy


async def resolve_policy(session: AsyncSession, *, strategy_id: int | None = None) -> RiskPolicy:
    """取生效阈值：策略级优先，缺省回落到全局。"""

    if strategy_id is not None:
        scoped = await get_policy(session, scope="strategy", strategy_id=strategy_id)
        if scoped is not None:
            return scoped
    return await get_or_create_policy(session)


async def resolve_policy_readonly(
    session: AsyncSession, *, strategy_id: int | None = None
) -> tuple[RiskPolicy, str]:
    """只读取生效阈值, 任何情况下都不落库。

    返回 `(policy, source)`: `source="stored"` 表示读到既有记录, `source="defaults"`
    表示用配置默认值构造了一份**未落库**的临时对象 (版本号为 None)。
    只读问答 (如 `/ai/query` 问风控) 必须用它, 不能为满足查询而写 `risk.risk_policy`。
    """

    if strategy_id is not None:
        scoped = await get_policy(session, scope="strategy", strategy_id=strategy_id)
        if scoped is not None:
            return scoped, "stored"
    existing = await get_policy(session)
    if existing is not None:
        return existing, "stored"
    defaults = RiskPolicy(
        scope="global",
        strategy_id=None,
        version=None,
        updated_by="system:defaults",
        note="默认阈值 (未落库)",
        **thresholds_from_settings(get_settings()),
    )
    return defaults, "defaults"


async def update_policy(
    session: AsyncSession,
    *,
    thresholds: dict[str, Decimal],
    expected_version: int,
    updated_by: str,
    note: str | None = None,
    scope: str = "global",
    strategy_id: int | None = None,
) -> RiskPolicy:
    current = await get_or_create_policy(session, scope=scope, strategy_id=strategy_id)
    if expected_version != current.version:
        raise RiskError(
            "risk_policy_stale",
            "阈值版本已过期, 请重新读取后再提交",
            status_code=409,
            details={"current_version": current.version, "expected_version": expected_version},
        )
    validate_thresholds(dict(thresholds))

    policy = RiskPolicy(
        scope=scope,
        strategy_id=strategy_id,
        version=current.version + 1,
        updated_by=updated_by,
        note=note,
        **{field: thresholds[field] for field in THRESHOLD_FIELDS},
    )
    session.add(policy)
    try:
        await session.commit()
    except IntegrityError as exc:  # 并发写入同版本
        await session.rollback()
        raise RiskError(
            "risk_policy_stale",
            "阈值版本已被并发修改",
            status_code=409,
            details={"expected_version": expected_version},
        ) from exc
    await session.refresh(policy)
    return policy


# ---------------------------------------------------------------------------
# 事件
# ---------------------------------------------------------------------------


def serialize_event(event: RiskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind,
        "severity": event.severity,
        "action": event.action,
        "strategy_id": event.strategy_id,
        "instrument_id": event.instrument_id,
        "policy_version": event.policy_version,
        "observed_value": _text(event.observed_value),
        "threshold": _text(event.threshold),
        "payload": event.payload,
        "evaluation_key": event.evaluation_key,
        "created_at": _iso(event.created_at),
        "resolved_at": _iso(event.resolved_at),
    }


def _event_filter(stmt: Any, column: Any, value: Any) -> Any:
    if value is None:
        return stmt.where(column.is_(None))
    return stmt.where(column == value)


async def _find_event(
    session: AsyncSession,
    *,
    kind: str,
    strategy_id: int | None,
    instrument_id: int | None,
    policy_version: int,
    evaluation_key: str,
) -> RiskEvent:
    stmt = select(RiskEvent).where(
        RiskEvent.kind == kind,
        RiskEvent.policy_version == policy_version,
        RiskEvent.evaluation_key == evaluation_key,
    )
    stmt = _event_filter(stmt, RiskEvent.strategy_id, strategy_id)
    stmt = _event_filter(stmt, RiskEvent.instrument_id, instrument_id)
    event = (await session.execute(stmt.limit(1))).scalar_one_or_none()
    if event is None:
        raise RiskError("risk_event_missing", "风控事件写入后无法回读", status_code=500)
    return event


async def record_event(
    session: AsyncSession,
    *,
    kind: str,
    severity: str,
    action: str,
    strategy_id: int | None,
    instrument_id: int | None,
    policy_version: int,
    observed_value: Decimal | None,
    threshold: Decimal | None,
    payload: dict[str, Any],
    evaluation_key: str,
    at: datetime | None = None,
) -> tuple[RiskEvent, bool]:
    """按五元组幂等写入一条风险事件。"""
    values: dict[str, Any] = {
        "kind": kind,
        "severity": severity,
        "action": action,
        "strategy_id": strategy_id,
        "instrument_id": instrument_id,
        "policy_version": policy_version,
        "observed_value": observed_value,
        "threshold": threshold,
        "payload": payload,
        "evaluation_key": evaluation_key,
    }
    if at is not None:
        values["created_at"] = at

    stmt = (
        pg_insert(RiskEvent)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_risk_event_key")
        .returning(RiskEvent.id)
    )
    event_id = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()
    if event_id is not None:
        event = await session.get(RiskEvent, event_id)
        if event is None:  # pragma: no cover - 插入后立即消失属数据库异常
            raise RiskError("risk_event_missing", "风控事件写入后无法回读", status_code=500)
        return event, True

    existing = await _find_event(
        session,
        kind=kind,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        policy_version=policy_version,
        evaluation_key=evaluation_key,
    )
    return existing, False


async def list_events(
    session: AsyncSession,
    *,
    kind: str | None = None,
    severity: str | None = None,
    strategy_id: int | None = None,
    since: datetime | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    stmt = select(RiskEvent)
    if kind is not None:
        stmt = stmt.where(RiskEvent.kind == kind)
    if severity is not None:
        stmt = stmt.where(RiskEvent.severity == severity)
    if strategy_id is not None:
        stmt = stmt.where(RiskEvent.strategy_id == strategy_id)
    if since is not None:
        stmt = stmt.where(RiskEvent.created_at >= _aware(since))
    if cursor is not None:
        stmt = stmt.where(RiskEvent.id < cursor)
    stmt = stmt.order_by(RiskEvent.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [serialize_event(row) for row in rows]
    next_cursor = str(rows[-1].id) if len(rows) == limit else None
    return {"items": items, "next_cursor": next_cursor}


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------


def _breach_instrument(breach: Breach) -> int | None:
    _, _, raw = breach.field.partition(":")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _base_result(
    *, strategy_id: int, key: str, policy: RiskPolicy, thresholds: dict[str, Decimal]
) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "evaluation_key": key,
        "policy_version": policy.version,
        "allowed": False,
        "reason": None,
        "capital": None,
        "limits": {field: _text(thresholds[field]) for field in THRESHOLD_FIELDS},
        "gross_exposure": None,
        "net_exposure": None,
        "leverage": None,
        "concentration": None,
        "drawdown": None,
        "drawdown_action": "none",
        "breaches": [],
        "events": [],
    }


async def evaluate(
    session: AsyncSession,
    *,
    strategy_id: int,
    as_of: datetime | None = None,
    evaluation_key: str | None = None,
    persist: bool = True,
    source: Any = None,
) -> dict[str, Any]:
    """对单个策略做一次完整风控评估。

    任何依赖缺失或计算异常都返回 ``allowed=False``，不会放行。
    """
    settings = get_settings()
    strategy = await data.load_strategy(session, strategy_id)
    if strategy is None:
        raise RiskError("not_found", f"策略 {strategy_id} 不存在", status_code=404)
    if strategy.status != "approved":
        raise RiskError(
            "strategy_not_approved",
            "策略未通过审批, 风控不做放行评估",
            status_code=409,
            details={"status": strategy.status},
        )

    moment = _aware(as_of)
    key = evaluation_key or moment.date().isoformat()
    policy = await resolve_policy(session, strategy_id=strategy_id)
    thresholds = policy_thresholds(policy)
    result = _base_result(strategy_id=strategy_id, key=key, policy=policy, thresholds=thresholds)

    legs = await data.load_legs(session, strategy_id)
    if not legs:
        result["reason"] = "risk_empty_portfolio"
        return result

    since = moment - timedelta(days=settings.risk_market_data_lookback_days)
    missing: list[str] = []
    for leg in legs:
        available = await data.has_recent_confirmed_candle(
            session, leg.instrument_id, bar="1d", since=since
        )
        if not available:
            missing.append(leg.inst_id)
    if missing:
        result["reason"] = "market_data_unavailable"
        result["details"] = {"missing": missing}
        return result

    baseline = await data.latest_backtest_run(session, strategy_id)
    if baseline is None:
        result["reason"] = "no_equity_series"
        return result
    points = await data.load_equity_series(session, baseline.id)
    if not points:
        result["reason"] = "no_equity_series"
        return result

    capital = baseline.initial_capital
    if capital <= ZERO:
        capital = _decimal(settings.risk_default_capital)
    result["capital"] = _text(capital)

    try:
        limit_values = _limits_from(thresholds)
        intents = tuple(
            LegIntent(
                instrument_id=leg.instrument_id,
                side=leg.side,
                weight=leg.target_weight,
                notional=leg.target_weight * capital,
            )
            for leg in legs
        )
        verdict = limits.evaluate_limits(legs=intents, limits=limit_values, capital=capital)
        positions = tuple(
            portfolio.Position(
                strategy_id=strategy_id,
                instrument_id=leg.instrument_id,
                side=leg.side,
                weight=leg.target_weight,
                notional=leg.target_weight * capital,
            )
            for leg in legs
        )
        portfolio_risk = portfolio.evaluate_portfolio(positions, capital=capital)
        equity_values = tuple(point.equity for point in points)
        peak, _ = drawdown.drawdown_series(equity_values)
        drawdown_verdict = drawdown.evaluate_drawdown(
            equity=equity_values[-1],
            peak=peak,
            thresholds=DrawdownThresholds(
                warn=thresholds["drawdown_warn"],
                reduce=thresholds["drawdown_reduce"],
                close=thresholds["drawdown_close"],
            ),
        )
    except RiskError:
        raise
    except Exception:  # 任何计算异常都 fail-closed
        result["reason"] = "risk_evaluation_failed"
        return result

    result["gross_exposure"] = _text(verdict.gross_exposure)
    result["net_exposure"] = _text(verdict.net_exposure)
    result["leverage"] = _text(verdict.leverage)
    result["concentration"] = _text(portfolio_risk.concentration)
    result["drawdown"] = _text(drawdown_verdict.drawdown)
    result["drawdown_action"] = drawdown_verdict.action
    result["breaches"] = [
        {
            "code": breach.code,
            "field": breach.field,
            "observed": _text(breach.observed),
            "threshold": _text(breach.threshold),
        }
        for breach in verdict.breaches
    ]
    result["allowed"] = not verdict.breaches and not drawdown_verdict.breached
    if not result["allowed"]:
        result["reason"] = "limit_breach" if verdict.breaches else "drawdown"

    if persist:
        events: list[RiskEvent] = []
        for breach in verdict.breaches:
            event, _ = await record_event(
                session,
                kind="limit_breach",
                severity="tier2",
                action="warn",
                strategy_id=strategy_id,
                instrument_id=_breach_instrument(breach),
                policy_version=policy.version,
                observed_value=breach.observed,
                threshold=breach.threshold,
                payload={"code": breach.code, "field": breach.field},
                evaluation_key=f"{key}#{breach.code}",
                at=moment,
            )
            events.append(event)
        if drawdown_verdict.breached:
            severity = drawdown_verdict.severity or "tier1"
            drawdown_threshold = {
                "tier3": thresholds["drawdown_close"],
                "tier2": thresholds["drawdown_reduce"],
                "tier1": thresholds["drawdown_warn"],
            }[severity]
            event, _ = await record_event(
                session,
                kind="drawdown",
                severity=severity,
                action=drawdown_verdict.action,
                strategy_id=strategy_id,
                instrument_id=None,
                policy_version=policy.version,
                observed_value=drawdown_verdict.drawdown,
                threshold=drawdown_threshold,
                payload={"action": drawdown_verdict.action},
                evaluation_key=f"{key}#drawdown",
                at=moment,
            )
            events.append(event)
        result["events"] = [
            serialize_event(event) for event in sorted(events, key=lambda item: item.id)
        ]

    return result


async def status(session: AsyncSession, *, strategy_id: int | None = None) -> dict[str, Any]:
    """只读状态查询：当前是否允许增加敞口、命中哪些限额。

    不写事件、不查 K 线、也不为缺省阈值落库, 用于面板与助手快速展示。
    """
    settings = get_settings()
    policy, policy_source = await resolve_policy_readonly(session, strategy_id=strategy_id)
    thresholds = policy_thresholds(policy)
    limit_values = _limits_from(thresholds)
    default_capital = _decimal(settings.risk_default_capital)

    positions: list[portfolio.Position] = []
    scope = "global"
    reason: str | None = None
    allowed = True

    if strategy_id is not None:
        scope = "strategy"
        strategy = await data.load_strategy(session, strategy_id)
        if strategy is None:
            raise RiskError("not_found", f"策略 {strategy_id} 不存在", status_code=404)
        legs = await data.load_legs(session, strategy_id)
        baseline = await data.latest_backtest_run(session, strategy_id)
        capital = baseline.initial_capital if baseline else default_capital
        if capital <= ZERO:
            capital = default_capital
        positions = [
            portfolio.Position(
                strategy_id=strategy_id,
                instrument_id=leg.instrument_id,
                side=leg.side,
                weight=leg.target_weight,
                notional=leg.target_weight * capital,
            )
            for leg in legs
        ]
        if strategy.status != "approved":
            allowed, reason = False, "strategy_not_approved"
        elif not legs:
            allowed, reason = False, "risk_empty_portfolio"
    else:
        total_capital = ZERO
        for approved_id in await data.list_approved_strategies(session):
            legs = await data.load_legs(session, approved_id)
            baseline = await data.latest_backtest_run(session, approved_id)
            capital = baseline.initial_capital if baseline else default_capital
            if capital <= ZERO:
                capital = default_capital
            total_capital += capital
            positions.extend(
                portfolio.Position(
                    strategy_id=approved_id,
                    instrument_id=leg.instrument_id,
                    side=leg.side,
                    weight=leg.target_weight,
                    notional=leg.target_weight * capital,
                )
                for leg in legs
            )
        capital = total_capital if total_capital > ZERO else default_capital

    try:
        portfolio_risk = portfolio.evaluate_portfolio(tuple(positions), capital=capital)
        breaches = portfolio.portfolio_breaches(portfolio_risk, limit_values, capital=capital)
        if strategy_id is not None:
            verdict = limits.evaluate_limits(
                legs=tuple(
                    LegIntent(
                        instrument_id=position.instrument_id,
                        side=position.side,
                        weight=position.weight,
                        notional=position.notional,
                    )
                    for position in positions
                ),
                limits=limit_values,
                capital=capital,
            )
            breaches = verdict.breaches or breaches
    except RiskError:
        raise
    except Exception:  # 计算失败一律拒绝放行
        return {
            "scope": scope,
            "strategy_id": strategy_id,
            "policy_version": policy.version,
            "policy_source": policy_source,
            "allowed": False,
            "reason": "risk_evaluation_failed",
            "limits": {field: _text(thresholds[field]) for field in THRESHOLD_FIELDS},
            "capital": _text(capital),
            "gross_exposure": None,
            "net_exposure": None,
            "leverage": None,
            "concentration": None,
            "long_exposure": None,
            "short_exposure": None,
            "long_short_conflicts": [],
            "duplicates": [],
            "breaches": [],
        }

    if reason is None and breaches:
        allowed, reason = False, "limit_breach"

    return {
        "scope": scope,
        "strategy_id": strategy_id,
        "policy_version": policy.version,
        "policy_source": policy_source,
        "allowed": allowed,
        "reason": reason,
        "limits": {field: _text(thresholds[field]) for field in THRESHOLD_FIELDS},
        "capital": _text(capital),
        "gross_exposure": _text(portfolio_risk.gross_exposure),
        "net_exposure": _text(portfolio_risk.net_exposure),
        "leverage": _text(portfolio_risk.gross_exposure / capital if capital > ZERO else ZERO),
        "concentration": _text(portfolio_risk.concentration),
        "long_exposure": _text(portfolio_risk.long_exposure),
        "short_exposure": _text(portfolio_risk.short_exposure),
        "long_short_conflicts": list(portfolio_risk.long_short_conflicts),
        "duplicates": [
            {
                "instrument_id": item.instrument_id,
                "side": item.side,
                "strategy_ids": list(item.strategy_ids),
            }
            for item in portfolio_risk.duplicates
        ],
        "breaches": [
            {
                "code": breach.code,
                "field": breach.field,
                "observed": _text(breach.observed),
                "threshold": _text(breach.threshold),
            }
            for breach in breaches
        ],
    }


async def observe_funding(
    session: AsyncSession,
    *,
    source: Any,
    strategy_id: int | None = None,
    inst_ids: tuple[str, ...] | None = None,
    evaluation_key: str | None = None,
    as_of: datetime | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """采集资金费率与盘口深度；任一标的缺数据即 503 fail-closed。"""
    if inst_ids is None:
        if strategy_id is not None:
            legs = await data.load_legs(session, strategy_id)
            inst_ids = tuple(dict.fromkeys(leg.inst_id for leg in legs))
        else:
            collected: list[str] = []
            for approved_id in await data.list_approved_strategies(session):
                for leg in await data.load_legs(session, approved_id):
                    collected.append(leg.inst_id)
            inst_ids = tuple(dict.fromkeys(collected))

    if not inst_ids:
        return {"items": [], "breaches": [], "events": [], "missing": []}

    policy = await resolve_policy(session, strategy_id=strategy_id)
    thresholds = policy_thresholds(policy)

    observations: list[FundingObservation] = []
    missing: list[str] = []
    for inst_id in inst_ids:
        quote = await source.observe(inst_id)
        if quote is None:
            missing.append(inst_id)
            continue
        rate = funding.parse_funding(quote.funding_payload)
        book = funding.parse_orderbook(quote.book_payload)
        if rate is None or book is None:
            missing.append(inst_id)
            continue
        observations.append(
            FundingObservation(
                inst_id=inst_id,
                funding_rate=rate.funding_rate,
                next_funding_at=rate.next_funding_at,
                best_bid=book.best_bid,
                best_ask=book.best_ask,
                bid_depth=book.bid_depth,
                ask_depth=book.ask_depth,
            )
        )

    if missing:
        raise RiskError(
            "risk_market_data_unavailable",
            "资金费率或盘口数据不可用, 风控拒绝放行",
            status_code=503,
            details={"missing": missing},
        )

    signals = funding.evaluate_market_health(
        tuple(observations),
        FundingThresholds(
            max_abs_funding_rate=thresholds["funding_rate_threshold"],
            min_depth_notional=thresholds["min_depth_notional"],
        ),
    )

    moment = _aware(as_of)
    key = evaluation_key or moment.date().isoformat()
    events: list[RiskEvent] = []
    if persist and signals:
        instrument_map = await data.instrument_ids_by_inst_id(
            session, tuple(observation.inst_id for observation in observations)
        )
        for signal in signals:
            event, _ = await record_event(
                session,
                kind=signal.kind,
                severity=signal.severity,
                action=signal.action,
                strategy_id=strategy_id,
                instrument_id=instrument_map.get(signal.inst_id),
                policy_version=policy.version,
                observed_value=signal.observed_value,
                threshold=signal.threshold,
                payload={**signal.payload, "inst_id": signal.inst_id},
                evaluation_key=f"{key}#{signal.kind}",
                at=moment,
            )
            events.append(event)

    return {
        "items": [
            {
                "inst_id": observation.inst_id,
                "funding_rate": _text(observation.funding_rate),
                "next_funding_at": observation.next_funding_at,
                "best_bid": _text(observation.best_bid),
                "best_ask": _text(observation.best_ask),
                "bid_depth": _text(observation.bid_depth),
                "ask_depth": _text(observation.ask_depth),
            }
            for observation in observations
        ],
        "breaches": [
            {
                "kind": signal.kind,
                "severity": signal.severity,
                "action": signal.action,
                "inst_id": signal.inst_id,
                "observed_value": _text(signal.observed_value),
                "threshold": _text(signal.threshold),
            }
            for signal in signals
        ],
        "events": [serialize_event(event) for event in sorted(events, key=lambda item: item.id)],
        "missing": [],
    }


async def scan(
    session: AsyncSession, *, source: Any = None, as_of: datetime | None = None
) -> dict[str, Any]:
    """巡检：对全部 approved 策略评估，并可选采集资金费率/流动性。"""
    results: list[dict[str, Any]] = []
    for strategy_id in await data.list_approved_strategies(session):
        try:
            outcome = await evaluate(session, strategy_id=strategy_id, as_of=as_of)
        except RiskError as exc:
            results.append({"strategy_id": strategy_id, "allowed": False, "reason": exc.code})
            continue
        results.append(
            {
                "strategy_id": strategy_id,
                "allowed": outcome["allowed"],
                "reason": outcome["reason"],
            }
        )

    funding_breaches = 0
    missing: list[str] = []
    if source is not None:
        try:
            observed = await observe_funding(session, source=source, as_of=as_of)
            funding_breaches = len(observed["breaches"])
        except RiskError as exc:
            missing = list(exc.details.get("missing", []))

    return {
        "status": "ok",
        "evaluated": len(results),
        "denied": sum(1 for item in results if not item["allowed"]),
        "funding_breaches": funding_breaches,
        "missing_market_data": missing,
        "results": results,
    }


__all__ = [
    "THRESHOLD_FIELDS",
    "evaluate",
    "get_or_create_policy",
    "get_policy",
    "list_events",
    "observe_funding",
    "policy_thresholds",
    "policy_view",
    "record_event",
    "resolve_policy",
    "resolve_policy_readonly",
    "scan",
    "serialize_event",
    "status",
    "thresholds_from_settings",
    "update_policy",
    "validate_thresholds",
]
