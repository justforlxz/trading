"""MCP 工具面:只读工具与受控操作工具.

分工与既有分层一致:本模块只做参数校验,编排与结果整理,业务计算与落库
一律调用 `app.market` / `app.research` / `app.opportunity` / `app.strategy` /
`app.backtest` / `app.risk` / `app.execution` 的 service.

刻意**不提供**的能力(架构性约束,由工具清单本身保证):

* 裸下单(`place_order`)——所有订单必须归属某个策略;
* `approve_strategy` / `live_authorize` / `set_risk_limit` / `toggle_live_trading`
  ——授权类动作只能由人在 Web 上完成;
* 任何生成结论文字或理解自然语言的工具.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.okx.rate_limit import UpstreamError, UpstreamUnavailable
from app.backtest import service as backtest_service
from app.backtest.costs import CostModel
from app.backtest.engine import Window
from app.config import Settings, get_settings
from app.execution import service as execution_service
from app.execution.core import positions as position_core
from app.execution.errors import ExecutionError
from app.jobs import queue as job_queue
from app.jobs import runs as job_runs
from app.jobs import tasks
from app.market import candles as candle_service
from app.market import instruments as instrument_service
from app.market.core.bars import normalize_bar
from app.market.core.calendar import session_phase
from app.market.models import Candle, DataQualityIssue
from app.mcp.core.actions import ActionError, parse_quantity, plan_action
from app.mcp.models import SCOPE_OPERATE, SCOPE_READ, McpClient
from app.mcp.resources import backtest_payload
from app.opportunity import query as opportunity_query
from app.opportunity import scanner
from app.research import relations as relation_service
from app.research import relative_strength as relative_strength_service
from app.research import targets as target_service
from app.risk import service as risk_service
from app.strategy import service as strategy_service
from app.strategy.models import Strategy
from app.strategy.schemas import (
    CreateStrategyRequest,
    LegInput,
    PatchStrategyRequest,
    StrategyKind,
    StrategyStatus,
)

SCAN_JOB_NAME = "mcp_trigger_scan"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
CLIENT_ORDER_ID_PREFIX = "mcp"


class ToolError(Exception):
    """工具失败:`code` 写进审计并作为结构化错误的 `error.code`."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(slots=True)
class ToolContext:
    session: AsyncSession
    client: McpClient


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    scope: str
    input_schema: dict[str, Any]
    handler: Handler

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _invalid(key: str, expect: str) -> ToolError:
    return ToolError("invalid_arguments", f"{key} 必须是{expect}", details={"argument": key})


def _arg_str(args: dict[str, Any], key: str, *, required: bool = False) -> str | None:
    value = args.get(key)
    if value is None:
        if required:
            raise ToolError("invalid_arguments", f"缺少必填参数: {key}", details={"argument": key})
        return None
    if not isinstance(value, str) or not value.strip():
        raise _invalid(key, "非空字符串")
    return value.strip()


def _arg_int(
    args: dict[str, Any], key: str, *, required: bool = False, minimum: int = 1
) -> int | None:
    value = args.get(key)
    if value is None:
        if required:
            raise ToolError("invalid_arguments", f"缺少必填参数: {key}", details={"argument": key})
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise _invalid(key, "整数")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _invalid(key, "整数") from None
    if number < minimum:
        raise _invalid(key, f"不小于 {minimum} 的整数")
    return number


def _arg_limit(args: dict[str, Any], *, default: int = DEFAULT_LIMIT) -> int:
    value = _arg_int(args, "limit", minimum=1)
    return default if value is None else min(value, MAX_LIMIT)


def _arg_bool(args: dict[str, Any], key: str, *, default: bool) -> bool:
    value = args.get(key)
    return default if value is None else bool(value)


def _arg_moment(args: dict[str, Any], key: str) -> datetime | None:
    raw = _arg_str(args, key)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise _invalid(key, "ISO-8601 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(key, "带时区的 ISO-8601 时间")
    return parsed


def _arg_decimal(args: dict[str, Any], key: str) -> Decimal | None:
    value = args.get(key)
    if value is None:
        return None
    number = parse_quantity(value)
    if number is None:
        raise _invalid(key, "正数")
    return number


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _num(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(Decimal(value).normalize(), "f")


def _settings() -> Settings:
    return get_settings()


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------


async def market_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    session = ctx.session
    settings = _settings()
    instruments = await instrument_service.count_instruments(session)
    latest_candle = await session.scalar(
        select(func.max(Candle.open_time)).where(Candle.confirm.is_(True))
    )
    unresolved = await session.scalar(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(DataQualityIssue.resolved_at.is_(None))
    )
    mode = execution_service.mode_view()
    return {
        "mode": mode["mode"],
        "real_trading_enabled": mode["real_trading_enabled"],
        "credentials_configured": mode["credentials_configured"],
        "session": session_phase(datetime.now(UTC)),
        "instruments": instruments,
        "latest_confirmed_candle": _iso(latest_candle),
        "unresolved_data_issues": int(unresolved or 0),
        "analysis_bar": settings.opportunity_bar,
        "lookback_bars": settings.opportunity_lookback_bars,
    }


async def list_instruments(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    rows, next_cursor = await instrument_service.list_instruments(
        ctx.session,
        limit=_arg_limit(args),
        cursor=_arg_str(args, "cursor"),
        asset_class=_arg_str(args, "asset_class"),
        inst_category=_arg_int(args, "inst_category", minimum=0),
        query=_arg_str(args, "q"),
    )
    return {
        "items": [
            {
                "inst_id": row.inst_id,
                "inst_family": row.inst_family,
                "uly": row.uly,
                "inst_category": row.inst_category,
                "asset_class": row.asset_class,
                "exchange": row.exchange,
                "ct_val": _num(row.ct_val),
                "ct_val_ccy": row.ct_val_ccy,
                "lot_sz": _num(row.lot_sz),
                "min_sz": _num(row.min_sz),
                "tick_sz": _num(row.tick_sz),
                "lever": _num(row.lever),
                "state": row.state,
                "rule_type": row.rule_type,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


async def get_candles(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    inst_id = _arg_str(args, "inst_id", required=True)
    bar = _arg_str(args, "bar", required=True)
    try:
        rows, next_cursor = await candle_service.list_candles(
            ctx.session,
            inst_id=inst_id,
            bar=bar,
            start=_arg_moment(args, "start"),
            end=_arg_moment(args, "end"),
            limit=_arg_limit(args),
            cursor=_arg_moment(args, "cursor"),
        )
    except ValueError as error:
        raise ToolError("unsupported_bar", str(error)) from error
    return {
        "inst_id": inst_id,
        "bar": bar,
        "items": [
            {
                "inst_id": inst_id,
                "bar": row.bar,
                "open_time": _iso(row.open_time),
                "open": _num(row.open),
                "high": _num(row.high),
                "low": _num(row.low),
                "close": _num(row.close),
                "vol": _num(row.vol),
                "vol_ccy": _num(row.vol_ccy),
                "vol_ccy_quote": _num(row.vol_ccy_quote),
                "confirm": row.confirm,
                "source": row.source,
            }
            for row in rows
        ],
        "next_cursor": _iso(next_cursor),
    }


async def data_coverage(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    inst_id = _arg_str(args, "inst_id", required=True)
    bar = _arg_str(args, "bar", required=True)
    try:
        normalized = normalize_bar(bar)
    except ValueError as error:
        raise ToolError("unsupported_bar", str(error)) from error
    instrument = await instrument_service.get_instrument(ctx.session, inst_id)
    if instrument is None:
        raise ToolError("instrument_not_found", f"unknown inst_id: {inst_id}")
    end = _arg_moment(args, "end") or datetime.now(UTC)
    start = _arg_moment(args, "start") or end - timedelta(days=30 if normalized == "1d" else 3)
    payload = await candle_service.coverage(
        ctx.session, instrument=instrument, bar=normalized, start=start, end=end
    )
    payload["window_start"] = _iso(payload["window_start"])
    payload["window_end"] = _iso(payload["window_end"])
    return payload


async def list_targets(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    rows, next_cursor = await target_service.list_targets(
        ctx.session,
        enabled=_arg_bool(args, "enabled", default=True),
        limit=_arg_limit(args),
        cursor=_arg_int(args, "cursor"),
    )
    return {
        "items": [
            {
                "id": row.id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "display_name": row.display_name,
                "note": row.note,
                "instrument_id": row.instrument_id,
                "enabled": row.enabled,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


async def get_target(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    target_id = _arg_int(args, "target_id", required=True)
    row = await target_service.get_target(ctx.session, target_id)
    if row is None:
        raise ToolError("target_not_found", f"unknown target_id: {target_id}")
    return {
        "id": row.id,
        "symbol": row.symbol,
        "exchange": row.exchange,
        "display_name": row.display_name,
        "note": row.note,
        "instrument_id": row.instrument_id,
        "enabled": row.enabled,
        "created_at": _iso(row.created_at),
    }


async def get_relations(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    target_id = _arg_int(args, "target_id", required=True)
    if await target_service.get_target(ctx.session, target_id) is None:
        raise ToolError("target_not_found", f"unknown target_id: {target_id}")
    snapshot = await relation_service.latest_snapshot(
        ctx.session, target_id, as_of=_arg_moment(args, "as_of")
    )
    if snapshot is None:
        return {
            "status": relation_service.STATUS_UNDEFINED,
            "reason": "no_snapshot: 尚未计算过关系快照",
            "snapshot": None,
            "edges": [],
            "significant_changes": [],
        }
    return await relation_service.build_relations_payload(
        ctx.session, snapshot, threshold=_settings().relation_change_threshold
    )


async def get_relative_strength(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    target_id = _arg_int(args, "target_id", required=True)
    counterparty = _arg_str(args, "counterparty", required=True)
    target = await target_service.get_target(ctx.session, target_id)
    if target is None:
        raise ToolError("target_not_found", f"unknown target_id: {target_id}")
    instrument = await instrument_service.get_instrument(ctx.session, counterparty)
    if instrument is None:
        raise ToolError("instrument_not_found", f"unknown inst_id: {counterparty}")
    price_basis = _arg_str(args, "price_basis") or "okx_close"
    if price_basis not in {"okx_close", "equity_close"}:
        raise _invalid("price_basis", "okx_close 或 equity_close")
    lookback = _arg_int(args, "lookback", minimum=2) or _settings().relative_strength_lookback
    return await relative_strength_service.compute_relative_strength(
        ctx.session,
        target=target,
        counterparty=instrument,
        lookback=lookback,
        price_basis=price_basis,
    )


async def list_opportunities(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    kind = _arg_str(args, "kind")
    if kind is not None and kind not in {"directional", "relative_value"}:
        raise _invalid("kind", "directional 或 relative_value")
    direction = _arg_str(args, "direction")
    if direction is not None and direction not in {"long", "short", "pair"}:
        raise _invalid("direction", "long / short / pair")
    min_score = args.get("min_score")
    if min_score is not None and (
        isinstance(min_score, bool) or not isinstance(min_score, int | float | str)
    ):
        raise _invalid("min_score", "数字")
    try:
        return await opportunity_query.list_opportunities_view(
            ctx.session,
            run_id=_arg_int(args, "run_id"),
            kind=kind,
            direction=direction,
            min_score=None if min_score is None else float(min_score),
            limit=_arg_limit(args),
            cursor=_arg_str(args, "cursor"),
        )
    except opportunity_query.InvalidCursor as error:
        raise ToolError("invalid_cursor", str(error)) from error


async def get_opportunity(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    opportunity_id = _arg_int(args, "opportunity_id", required=True)
    payload = await opportunity_query.get_opportunity_view(ctx.session, opportunity_id)
    if payload is None:
        raise ToolError("opportunity_not_found", f"unknown opportunity_id: {opportunity_id}")
    return payload


async def list_strategies(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    status = _arg_str(args, "status")
    if status is not None and status not in {item.value for item in StrategyStatus}:
        raise _invalid("status", "策略状态枚举值")
    kind = _arg_str(args, "kind")
    if kind is not None and kind not in {item.value for item in StrategyKind}:
        raise _invalid("kind", "directional 或 relative_value")
    cursor = _arg_int(args, "cursor")
    rows, next_cursor = await strategy_service.list_strategies(
        ctx.session, status=status, kind=kind, limit=_arg_limit(args), cursor=cursor
    )
    ids = [row.id for row in rows]
    reviewers = await strategy_service.latest_reviewers(ctx.session, ids)
    legs_by_strategy = await strategy_service.load_legs_many(ctx.session, ids)
    return {
        "items": [
            strategy_service.strategy_payload(
                row,
                legs=legs_by_strategy.get(row.id, []),
                reviewer=reviewers.get(row.id),
            )
            for row in rows
        ],
        "next_cursor": None if next_cursor is None else str(next_cursor),
    }


async def get_strategy(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    strategy_id = _arg_int(args, "strategy_id", required=True)
    return await strategy_service.strategy_detail(ctx.session, strategy_id)


async def get_backtest(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    backtest_id = _arg_int(args, "backtest_id", required=True)
    return await backtest_payload(ctx.session, backtest_id)


async def risk_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await risk_service.status(ctx.session, strategy_id=_arg_int(args, "strategy_id"))


async def list_risk_events(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await risk_service.list_events(
        ctx.session,
        kind=_arg_str(args, "kind"),
        severity=_arg_str(args, "severity"),
        strategy_id=_arg_int(args, "strategy_id"),
        since=_arg_moment(args, "since"),
        limit=_arg_limit(args),
        cursor=_arg_int(args, "cursor"),
    )


async def list_positions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await execution_service.positions_view(
        ctx.session, strategy_id=_arg_int(args, "strategy_id")
    )


async def list_orders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await execution_service.list_orders(
        ctx.session,
        strategy_id=_arg_int(args, "strategy_id"),
        state=_arg_str(args, "state"),
        mode=_arg_str(args, "mode"),
        limit=_arg_limit(args),
        cursor=_arg_int(args, "cursor"),
    )


async def virtual_positions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """策略级虚拟持仓:按策略聚合持仓,已实现与浮动盈亏."""

    valuations = await execution_service.position_valuations(
        ctx.session, strategy_id=_arg_int(args, "strategy_id")
    )
    grouped: dict[int, list[position_core.PositionValuation]] = {}
    for item in valuations:
        grouped.setdefault(item.strategy_id, []).append(item)
    by_strategy = []
    for strategy_id in sorted(grouped):
        totals = position_core.account_totals(grouped[strategy_id])
        by_strategy.append(
            {
                "strategy_id": strategy_id,
                "positions": totals.positions,
                "realized_pnl": _num(totals.realized_pnl),
                "unrealized_pnl": _num(totals.unrealized_pnl),
                "total_pnl": _num(totals.total_pnl),
                "gross_notional": _num(totals.gross_notional),
                "net_notional": _num(totals.net_notional),
            }
        )
    return {
        "items": [execution_service.serialize_valuation(item) for item in valuations],
        "by_strategy": by_strategy,
    }


# ---------------------------------------------------------------------------
# 操作工具
# ---------------------------------------------------------------------------


def _actor(ctx: ToolContext) -> str:
    return f"mcp:{ctx.client.name}"


async def trigger_scan(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """同步执行一次扫描;`idempotency_key` 相同则不产生第二条批次.

    走 `ops.job_run` 作为幂等台账(与 API 的扫描任务同一个机制),但任务名
    独立为 `mcp_trigger_scan`,不会与 arq 的 `scan_opportunities` 互相顶掉.
    """

    key = _arg_str(args, "idempotency_key", required=True)
    as_of = _arg_moment(args, "as_of")
    universe = args.get("universe")
    if universe is not None and (
        not isinstance(universe, list) or any(not isinstance(item, str) for item in universe)
    ):
        raise _invalid("universe", "字符串数组")
    raw_params = args.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        raise _invalid("params", "对象")

    job, created = await job_runs.create_run(
        ctx.session,
        job_name=SCAN_JOB_NAME,
        payload={
            "idempotency_key": key,
            "as_of": _iso(as_of),
            "universe": sorted(universe) if universe else None,
            "params": raw_params,
        },
    )
    if not created:
        return {
            "status": "skipped",
            "job_id": job.id,
            "run_id": (job.result or {}).get("run_id"),
            "idempotency_key": key,
        }

    await job_runs.mark_running(ctx.session, job.id)
    try:
        outcome = await scanner.scan(
            ctx.session,
            as_of=as_of,
            universe=universe,
            params=raw_params,
            settings=_settings(),
        )
    except (LookupError, ValueError) as error:
        await job_runs.finish_run(ctx.session, job.id, "failed", error=str(error))
        code = "scan_no_data" if isinstance(error, LookupError) else "scan_invalid_params"
        raise ToolError(code, str(error)) from error
    await job_runs.finish_run(
        ctx.session,
        job.id,
        "ok",
        result={"run_id": outcome.run.id, "counts": outcome.counts},
    )
    return {
        "status": outcome.status,
        "job_id": job.id,
        "run_id": outcome.run.id,
        "as_of": _iso(outcome.run.as_of),
        "counts": outcome.counts,
        "idempotency_key": key,
    }


async def create_strategy_draft(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    kind = _arg_str(args, "kind", required=True)
    if kind not in {item.value for item in StrategyKind}:
        raise _invalid("kind", "directional 或 relative_value")
    templates = args.get("templates")
    if (
        not isinstance(templates, list)
        or not templates
        or any(not isinstance(item, str) for item in templates)
    ):
        raise _invalid("templates", "非空字符串数组")
    raw_params = args.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        raise _invalid("params", "对象")
    payload = CreateStrategyRequest(
        kind=StrategyKind(kind),
        name=_arg_str(args, "name", required=True),
        target_id=_arg_int(args, "target_id"),
        templates=list(templates),
        params=dict(raw_params or {}),
    )
    strategy, created = await strategy_service.create_strategy(ctx.session, payload)
    legs = await strategy_service.load_legs(ctx.session, strategy.id)
    return {
        "created": created,
        "strategy": strategy_service.strategy_payload(strategy, legs=legs),
    }


async def update_strategy_draft(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    strategy_id = _arg_int(args, "strategy_id", required=True)
    raw_params = args.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        raise _invalid("params", "对象")
    raw_legs = args.get("legs")
    legs: list[LegInput] | None = None
    if raw_legs is not None:
        if not isinstance(raw_legs, list) or not raw_legs:
            raise _invalid("legs", "非空对象数组")
        try:
            legs = [LegInput.model_validate(item) for item in raw_legs]
        except ValueError as error:
            raise ToolError("invalid_arguments", f"legs 不合法: {error}") from error
    request = PatchStrategyRequest(name=_arg_str(args, "name"), params=raw_params, legs=legs)
    strategy = await strategy_service.patch_strategy(ctx.session, strategy_id, request)
    return await strategy_service.strategy_detail(ctx.session, strategy.id)


async def submit_strategy_for_approval(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    strategy_id = _arg_int(args, "strategy_id", required=True)
    reason = _arg_str(args, "reason")
    await strategy_service.transition(
        ctx.session,
        strategy_id,
        "submit",
        actor=_actor(ctx),
        reason=reason,
    )
    return await strategy_service.strategy_detail(ctx.session, strategy_id)


async def run_backtest(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    strategy_id = _arg_int(args, "strategy_id", required=True)
    raw_window = args.get("window")
    if not isinstance(raw_window, dict):
        raise _invalid("window", "对象(start/end)")
    window = _window_from(raw_window, default_name="main", default_role="eval")
    raw_windows = args.get("windows") or []
    if not isinstance(raw_windows, list):
        raise _invalid("windows", "对象数组")
    windows = tuple(
        _window_from(item, default_name=f"w{index}", default_role="eval")
        for index, item in enumerate(raw_windows, start=1)
        if isinstance(item, dict)
    )
    cost_model = _cost_model_from(args.get("cost_model"))
    raw_criteria = args.get("criteria")
    thresholds = None
    if isinstance(raw_criteria, dict):
        raw_thresholds = raw_criteria.get("thresholds") or []
        if not isinstance(raw_thresholds, list):
            raise _invalid("criteria.thresholds", "对象数组")
        thresholds = tuple(item for item in raw_thresholds if isinstance(item, dict))

    request = backtest_service.BacktestRequest(
        strategy_id=strategy_id,
        window=window,
        windows=windows,
        bar=_arg_str(args, "bar") or "1d",
        initial_capital=_arg_decimal(args, "initial_capital") or Decimal("100000"),
        cost_model=cost_model,
        thresholds=thresholds,
        annualization_factor=_arg_decimal(args, "annualization_factor"),
        risk_free_rate=_arg_decimal(args, "risk_free_rate") or Decimal("0"),
        rebalance=_arg_str(args, "rebalance") or "none",
    )
    run, created = await backtest_service.create(ctx.session, request)
    job, job_created = await job_runs.create_run(
        ctx.session, job_name=tasks.BACKTEST_RUN, payload={"backtest_id": run.id}
    )
    if job_created and run.status != "queued":
        await backtest_service.mark_queued(ctx.session, run)
    if job_created:
        await job_queue.enqueue_task(tasks.BACKTEST_RUN, run_id=job.id, backtest_id=run.id)
    return {
        "run_id": run.id,
        "job_id": job.id,
        "status": run.status,
        "run_key": run.run_key,
        "created": created,
        "dispatched": job_created,
    }


async def pause_strategy(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await _set_paused(ctx, args, paused=True)


async def resume_strategy(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await _set_paused(ctx, args, paused=False)


async def _set_paused(ctx: ToolContext, args: dict[str, Any], *, paused: bool) -> dict[str, Any]:
    strategy_id = _arg_int(args, "strategy_id", required=True)
    _require_live_authorized(strategy_id)
    strategy = await ctx.session.get(Strategy, strategy_id)
    if strategy is None:
        raise ToolError("strategy_not_found", f"unknown strategy_id: {strategy_id}")
    strategy.paused_at = datetime.now(tz=UTC) if paused else None
    await ctx.session.commit()
    return {
        "strategy_id": strategy_id,
        "paused": paused,
        "paused_at": _iso(strategy.paused_at),
    }


def _window_from(raw: dict[str, Any], *, default_name: str, default_role: str) -> Window:
    start = _moment_from_value(raw.get("start"), "window.start")
    end = _moment_from_value(raw.get("end"), "window.end")
    return Window(
        name=raw.get("name") or default_name,
        start=start,
        end=end,
        role=raw.get("role") or default_role,
    )


def _moment_from_value(value: Any, key: str) -> datetime:
    if not isinstance(value, str):
        raise _invalid(key, "ISO-8601 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _invalid(key, "ISO-8601 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(key, "带时区的 ISO-8601 时间")
    return parsed


def _cost_model_from(raw: Any) -> CostModel:
    defaults = CostModel()
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise _invalid("cost_model", "对象")
    values: dict[str, Any] = {}
    for key in ("taker_fee_bps", "maker_fee_bps", "slippage_bps", "funding_bps_per_period"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            values[key] = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise _invalid(f"cost_model.{key}", "数字") from error
    fee_role = raw.get("fee_role") or defaults.fee_role
    if fee_role not in {"taker", "maker"}:
        raise _invalid("cost_model.fee_role", "taker 或 maker")
    return CostModel(
        taker_fee_bps=values.get("taker_fee_bps", defaults.taker_fee_bps),
        maker_fee_bps=values.get("maker_fee_bps", defaults.maker_fee_bps),
        slippage_bps=values.get("slippage_bps", defaults.slippage_bps),
        funding_bps_per_period=values.get(
            "funding_bps_per_period", defaults.funding_bps_per_period
        ),
        funding_enabled=bool(raw.get("funding", defaults.funding_enabled)),
        fee_role=fee_role,
    )


def _require_live_authorized(strategy_id: int) -> None:
    if strategy_id not in execution_service.authorized_strategy_ids():
        raise ToolError(
            "not_live_authorized",
            "该策略未获实盘授权, 拒绝执行",
            details={"strategy_id": strategy_id},
        )


async def execute_strategy_action(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """受控执行:四道闸门按固定顺序判定,任何一步不通过都不落单."""

    strategy_id = _arg_int(args, "strategy_id", required=True)
    action = _arg_str(args, "action", required=True)
    reason = _arg_str(args, "reason", required=True)
    inst_id = _arg_str(args, "inst_id", required=True)
    side = _arg_str(args, "side")
    position_side = _arg_str(args, "position_side")
    order_type = _arg_str(args, "order_type") or "market"
    price = _arg_decimal(args, "price")
    idempotency_key = _arg_str(args, "idempotency_key")

    # 闸门 1:策略必须已获实盘授权(逐策略放行清单).
    _require_live_authorized(strategy_id)

    # 闸门 2:策略未暂停.
    strategy = await ctx.session.get(Strategy, strategy_id)
    if strategy is None:
        raise ToolError("strategy_not_found", f"unknown strategy_id: {strategy_id}")
    if strategy.paused_at is not None:
        raise ToolError(
            "strategy_paused",
            "策略已暂停, 拒绝执行",
            details={"strategy_id": strategy_id, "paused_at": _iso(strategy.paused_at)},
        )

    # 闸门 3:风控放行(fail-closed).
    await _risk_gate(ctx.session, strategy_id)

    instrument = await instrument_service.get_instrument(ctx.session, inst_id)
    if instrument is None:
        raise ToolError("instrument_not_found", f"unknown inst_id: {inst_id}")

    resolved_side = position_side or {"buy": "long", "sell": "short"}.get(side or "")
    available = None
    if resolved_side in {"long", "short"}:
        available = await execution_service.available_close_quantity(
            ctx.session,
            strategy_id=strategy_id,
            instrument_id=instrument.id,
            position_side=resolved_side,
        )
    try:
        plan = plan_action(
            action,
            side=side,
            position_side=position_side,
            quantity=args.get("quantity"),
            available=available,
        )
    except ActionError as error:
        raise ToolError(error.code, error.message, details=error.details) from error

    # 闸门 4:统一执行系统的幂等校验(同 idempotency_key 不重复落单).
    key = idempotency_key or f"{CLIENT_ORDER_ID_PREFIX}{uuid4().hex[:24]}"
    existing = await execution_service.load_by_client_order_id(ctx.session, key)
    if existing is not None:
        raise ToolError(
            "duplicate_request",
            "同一 idempotency_key 的订单已存在",
            details={"idempotency_key": key, "order_id": existing.id},
        )

    mode = execution_service.resolve_mode()
    try:
        order, created = await execution_service.submit_order(
            ctx.session,
            strategy_id=strategy_id,
            inst_id=inst_id,
            side=plan.side,
            position_side=plan.position_side,
            quantity=plan.quantity,
            order_type=order_type,
            price=price,
            reduce_only=plan.reduce_only,
            intent=plan.intent,
            client_order_id=key,
            mode=mode,
        )
    except (ExecutionError, UpstreamError, UpstreamUnavailable) as error:
        code = error.code if isinstance(error, ExecutionError) else "upstream_unavailable"
        message = error.message if isinstance(error, ExecutionError) else str(error)
        details = error.details if isinstance(error, ExecutionError) else {}
        raise ToolError(code, message, details=details) from error

    return {
        "action": action,
        "mode": mode,
        "reason": reason,
        "created": created,
        "idempotency_key": key,
        "order": order,
    }


async def _risk_gate(session: AsyncSession, strategy_id: int) -> None:
    """复用执行系统的风控闸门;把它的拒绝翻译成 MCP 的稳定错误码."""

    try:
        await execution_service.risk_gate(session, strategy_id)
    except ExecutionError as error:
        if error.code == "execution_strategy_not_approved":
            raise ToolError("not_approved", error.message, details=error.details) from error
        raise ToolError("risk_blocked", error.message, details=error.details) from error


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_INT = {"type": "integer"}
_STR = {"type": "string"}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="market_status",
        description="行情与执行环境概览:执行模式,美股时段,标的数量,数据新鲜度.",
        scope=SCOPE_READ,
        input_schema=_schema({}, []),
        handler=market_status,
    ),
    ToolSpec(
        name="list_instruments",
        description="分页列出 OKX 美股永续合约标的(含合约面值与最小下单量).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": {**_STR, "description": "上一页最后一条的 inst_id"},
                "asset_class": _STR,
                "inst_category": _INT,
                "q": {**_STR, "description": "inst_id 模糊匹配"},
            },
            [],
        ),
        handler=list_instruments,
    ),
    ToolSpec(
        name="get_candles",
        description="按标的与周期读取已入库 K 线(升序,含是否已确认).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "inst_id": _STR,
                "bar": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "4h", "1d"]},
                "start": {**_STR, "description": "ISO-8601,含"},
                "end": {**_STR, "description": "ISO-8601,不含"},
                "limit": {**_INT, "minimum": 1, "maximum": 300},
                "cursor": {**_STR, "description": "上一页最后一条的 open_time"},
            },
            ["inst_id", "bar"],
        ),
        handler=get_candles,
    ),
    ToolSpec(
        name="data_coverage",
        description="某标的某周期的数据覆盖率:应到/实到/缺失与逐日缺口.",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "inst_id": _STR,
                "bar": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "4h", "1d"]},
                "start": _STR,
                "end": _STR,
            },
            ["inst_id", "bar"],
        ),
        handler=data_coverage,
    ),
    ToolSpec(
        name="list_targets",
        description="分页列出目标股票(默认只看启用中的).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "enabled": {"type": "boolean"},
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": _INT,
            },
            [],
        ),
        handler=list_targets,
    ),
    ToolSpec(
        name="get_target",
        description="读取单个目标股票.",
        scope=SCOPE_READ,
        input_schema=_schema({"target_id": _INT}, ["target_id"]),
        handler=get_target,
    ),
    ToolSpec(
        name="get_relations",
        description="目标股票与对手方的相关性快照(无快照时 status=undefined 并给原因).",
        scope=SCOPE_READ,
        input_schema=_schema({"target_id": _INT, "as_of": _STR}, ["target_id"]),
        handler=get_relations,
    ),
    ToolSpec(
        name="get_relative_strength",
        description="目标股票相对单个对手方的强弱(比率,动量与序列).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "target_id": _INT,
                "counterparty": {**_STR, "description": "对手方 inst_id"},
                "lookback": {**_INT, "minimum": 2, "maximum": 500},
                "price_basis": {"type": "string", "enum": ["okx_close", "equity_close"]},
            },
            ["target_id", "counterparty"],
        ),
        handler=get_relative_strength,
    ),
    ToolSpec(
        name="list_opportunities",
        description="分页列出机会(默认最新批次,按分数倒序,含理由与证据).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "run_id": _INT,
                "kind": {"type": "string", "enum": ["directional", "relative_value"]},
                "direction": {"type": "string", "enum": ["long", "short", "pair"]},
                "min_score": {"type": "number"},
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": _STR,
            },
            [],
        ),
        handler=list_opportunities,
    ),
    ToolSpec(
        name="get_opportunity",
        description="读取单条机会详情(含成员列表).",
        scope=SCOPE_READ,
        input_schema=_schema({"opportunity_id": _INT}, ["opportunity_id"]),
        handler=get_opportunity,
    ),
    ToolSpec(
        name="list_strategies",
        description="分页列出策略(可按状态/类型过滤,含策略腿).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "status": {
                    "type": "string",
                    "enum": ["draft", "pending_approval", "approved", "rejected", "archived"],
                },
                "kind": {"type": "string", "enum": ["directional", "relative_value"]},
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": _INT,
            },
            [],
        ),
        handler=list_strategies,
    ),
    ToolSpec(
        name="get_strategy",
        description="读取单条策略详情(字段与 Web GET /api/v1/strategies/{id} 一致).",
        scope=SCOPE_READ,
        input_schema=_schema({"strategy_id": _INT}, ["strategy_id"]),
        handler=get_strategy,
    ),
    ToolSpec(
        name="get_backtest",
        description="读取单次回测的运行信息与指标.",
        scope=SCOPE_READ,
        input_schema=_schema({"backtest_id": _INT}, ["backtest_id"]),
        handler=get_backtest,
    ),
    ToolSpec(
        name="risk_status",
        description="当前风控结论:是否允许增加敞口,命中哪些限额,组合集中度.",
        scope=SCOPE_READ,
        input_schema=_schema({"strategy_id": _INT}, []),
        handler=risk_status,
    ),
    ToolSpec(
        name="list_risk_events",
        description="分页列出风控事件(按 id 倒序).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "kind": {
                    "type": "string",
                    "enum": ["limit_breach", "drawdown", "funding", "liquidity"],
                },
                "severity": {"type": "string", "enum": ["tier1", "tier2", "tier3"]},
                "strategy_id": _INT,
                "since": _STR,
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": _INT,
            },
            [],
        ),
        handler=list_risk_events,
    ),
    ToolSpec(
        name="list_positions",
        description="当前持仓与账户合计(标记价格估值).",
        scope=SCOPE_READ,
        input_schema=_schema({"strategy_id": _INT}, []),
        handler=list_positions,
    ),
    ToolSpec(
        name="list_orders",
        description="分页列出订单(可按策略/状态/模式过滤).",
        scope=SCOPE_READ,
        input_schema=_schema(
            {
                "strategy_id": _INT,
                "state": {
                    "type": "string",
                    "enum": ["pending", "submitted", "partial", "filled", "canceled", "rejected"],
                },
                "mode": {"type": "string", "enum": ["paper", "real"]},
                "limit": {**_INT, "minimum": 1, "maximum": MAX_LIMIT},
                "cursor": _INT,
            },
            [],
        ),
        handler=list_orders,
    ),
    ToolSpec(
        name="virtual_positions",
        description="策略级虚拟持仓:按策略聚合数量,已实现与浮动盈亏.",
        scope=SCOPE_READ,
        input_schema=_schema({"strategy_id": _INT}, []),
        handler=virtual_positions,
    ),
    ToolSpec(
        name="trigger_scan",
        description="同步触发一次全市场扫描;同 idempotency_key 不产生第二条批次.",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {
                "reason": {**_STR, "minLength": 1, "maxLength": 1000},
                "idempotency_key": {**_STR, "minLength": 1, "maxLength": 128},
                "as_of": _STR,
                "universe": {"type": "array", "items": _STR},
                "params": {"type": "object"},
            },
            ["idempotency_key", "reason"],
        ),
        handler=trigger_scan,
    ),
    ToolSpec(
        name="create_strategy_draft",
        description="按目标或机会生成策略草稿(status=draft).",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {
                "reason": {**_STR, "minLength": 1, "maxLength": 1000},
                "kind": {"type": "string", "enum": ["directional", "relative_value"]},
                "name": {**_STR, "minLength": 1, "maxLength": 200},
                "templates": {"type": "array", "items": _STR, "minItems": 1},
                "target_id": _INT,
                "params": {"type": "object"},
            },
            ["kind", "name", "templates", "reason"],
        ),
        handler=create_strategy_draft,
    ),
    ToolSpec(
        name="update_strategy_draft",
        description="修改草稿策略(仅 draft/rejected 可编辑,编辑后版本递增).",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {
                "reason": {**_STR, "minLength": 1, "maxLength": 1000},
                "strategy_id": _INT,
                "name": {**_STR, "minLength": 1, "maxLength": 200},
                "params": {"type": "object"},
                "legs": {"type": "array", "items": {"type": "object"}},
            },
            ["strategy_id", "reason"],
        ),
        handler=update_strategy_draft,
    ),
    ToolSpec(
        name="submit_strategy_for_approval",
        description="把草稿提交人工审批(draft -> pending_approval);不能代替人审批.",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {"strategy_id": _INT, "reason": {**_STR, "minLength": 1, "maxLength": 1000}},
            ["strategy_id", "reason"],
        ),
        handler=submit_strategy_for_approval,
    ),
    ToolSpec(
        name="run_backtest",
        description="提交一次历史回测(落库并排队,返回 run_id 与 job_id).",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {
                "reason": {**_STR, "minLength": 1, "maxLength": 1000},
                "strategy_id": _INT,
                "window": {
                    "type": "object",
                    "properties": {"start": _STR, "end": _STR, "name": _STR, "role": _STR},
                    "required": ["start", "end"],
                },
                "windows": {"type": "array", "items": {"type": "object"}},
                "bar": {"type": "string", "enum": ["1m", "5m", "15m", "1h", "4h", "1d"]},
                "initial_capital": {"type": ["string", "number"]},
                "cost_model": {"type": "object"},
                "criteria": {"type": "object"},
                "annualization_factor": {"type": ["string", "number"]},
                "risk_free_rate": {"type": ["string", "number"]},
                "rebalance": {"type": "string", "enum": ["none", "daily"]},
            },
            ["strategy_id", "window", "reason"],
        ),
        handler=run_backtest,
    ),
    ToolSpec(
        name="pause_strategy",
        description="暂停一个已获实盘授权的策略(只影响新的执行动作).",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {"strategy_id": _INT, "reason": {**_STR, "minLength": 1, "maxLength": 1000}},
            ["strategy_id", "reason"],
        ),
        handler=pause_strategy,
    ),
    ToolSpec(
        name="resume_strategy",
        description="恢复一个已获实盘授权的策略.",
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {"strategy_id": _INT, "reason": {**_STR, "minLength": 1, "maxLength": 1000}},
            ["strategy_id", "reason"],
        ),
        handler=resume_strategy,
    ),
    ToolSpec(
        name="execute_strategy_action",
        description=(
            "在策略名下执行 open/increase/reduce/close/stop;四道闸门"
            "(实盘授权,未暂停,风控放行,幂等)任一不通过即拒绝并记审计."
        ),
        scope=SCOPE_OPERATE,
        input_schema=_schema(
            {
                "strategy_id": _INT,
                "action": {
                    "type": "string",
                    "enum": ["open", "increase", "reduce", "close", "stop"],
                },
                "reason": {**_STR, "minLength": 1, "maxLength": 1000},
                "inst_id": _STR,
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "position_side": {"type": "string", "enum": ["long", "short"]},
                "quantity": {"type": ["string", "number"]},
                "order_type": {"type": "string", "enum": ["market", "limit"]},
                "price": {"type": ["string", "number"]},
                "idempotency_key": {**_STR, "maxLength": 32},
            },
            ["strategy_id", "action", "reason", "inst_id"],
        ),
        handler=execute_strategy_action,
    ),
)

TOOL_INDEX: dict[str, ToolSpec] = {tool.name: tool for tool in TOOLS}


def tool_definitions() -> list[dict[str, Any]]:
    return [tool.definition() for tool in TOOLS]


def get_tool(name: str) -> ToolSpec:
    tool = TOOL_INDEX.get(name)
    if tool is None:
        raise ToolError("unknown_tool", f"unknown tool: {name}", details={"tool": name})
    return tool


__all__ = [
    "MAX_LIMIT",
    "SCAN_JOB_NAME",
    "TOOLS",
    "TOOL_INDEX",
    "ToolContext",
    "ToolError",
    "ToolSpec",
    "get_tool",
    "tool_definitions",
]
