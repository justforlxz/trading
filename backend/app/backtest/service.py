"""回测服务：编排「校验输入 → 排队 → 执行 → 幂等落库」。

决策计算全部在 `costs` / `metrics` / `criteria` / `engine` 的纯函数里，这里只做
IO 与持久化：读策略行与已确认 K 线、按 `run_key` 去重、写指标/权益/成交。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest import criteria as criteria_rules
from app.backtest import data
from app.backtest import engine as engine_mod
from app.backtest.costs import CostModel
from app.backtest.engine import LegSpec, Simulation, Window
from app.backtest.errors import BacktestError
from app.backtest.metrics import METRIC_UNITS, compute_metrics, default_annualization_factor
from app.backtest.models import (
    BacktestEquityPoint,
    BacktestMetric,
    BacktestRun,
    BacktestTrade,
)
from app.config import Settings, get_settings
from app.db.session import session_factory
from app.market.core.bars import bar_seconds, normalize_bar

logger = logging.getLogger(__name__)

RUN_KEY_VERSION = "backtest/1"
DATA_SOURCE = "okx_usdt_perp_candle"
PRICE_BASIS = "okx_close"
FUNDING_ASSUMPTION = "constant"


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    """一次回测请求（已由 API 层解析，服务层不再依赖 HTTP 类型）。"""

    strategy_id: int
    window: Window
    windows: tuple[Window, ...]
    bar: str
    initial_capital: Decimal
    cost_model: CostModel
    thresholds: tuple[dict[str, Any], ...] | None = None
    annualization_factor: Decimal | None = None
    risk_free_rate: Decimal = Decimal(0)
    rebalance: str = "none"


def _text(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _text(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def digest(value: Any) -> str:
    payload = json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _normalize_windows(request: BacktestRequest) -> tuple[Window, list[Window]]:
    """主窗口是整段汇总，`windows` 是其中的独立评估段（可作 walk-forward 切分）。"""

    main = Window(
        name=request.window.name or "main",
        start=_aware(request.window.start),
        end=_aware(request.window.end),
        role=request.window.role or "eval",
    )
    segments = [
        Window(
            name=window.name or f"w{index}",
            start=_aware(window.start),
            end=_aware(window.end),
            role=window.role or "eval",
        )
        for index, window in enumerate(request.windows, start=1)
    ]
    engine_mod.validate_windows([main])
    if segments:
        engine_mod.validate_windows(segments)
        used = {main.name}
        for segment in segments:
            if segment.name in used:
                raise BacktestError(
                    "backtest_window_invalid",
                    f"duplicate window name: {segment.name!r}",
                    details={"name": segment.name},
                )
            used.add(segment.name)
            if segment.start < main.start or segment.end > main.end:
                raise BacktestError(
                    "backtest_window_out_of_range",
                    f"window {segment.name!r} is outside the main window",
                    details={"name": segment.name},
                )
    return main, segments


def _check_bar_and_span(bar: str, windows: Sequence[Window], settings: Settings) -> None:
    step = bar_seconds(bar)
    for window in windows:
        span = (window.end - window.start).total_seconds()
        bars = span / step
        if bars > settings.backtest_max_bars:
            raise BacktestError(
                "backtest_window_too_long",
                f"window {window.name!r} needs {bars:.0f} bars, limit is "
                f"{settings.backtest_max_bars}",
                details={
                    "name": window.name,
                    "bar": bar,
                    "bars": int(bars),
                    "max_bars": settings.backtest_max_bars,
                },
            )


def _normalized_payload(
    request: BacktestRequest,
    *,
    source: data.StrategySource,
    windows: Sequence[Window],
    bar: str,
    annualization_factor: Decimal,
) -> dict[str, Any]:
    """进入 `run_key` 的全部参数（含策略版本），保证同参数幂等。"""

    return {
        "version": RUN_KEY_VERSION,
        "strategy_id": source.id,
        "strategy_version": source.version,
        "strategy_content_hash": source.content_hash,
        "window": {
            "start": _iso(windows[0].start),
            "end": _iso(windows[0].end),
        },
        "windows": [
            {
                "name": window.name,
                "start": _iso(window.start),
                "end": _iso(window.end),
                "role": window.role,
            }
            for window in windows
        ],
        "bar": bar,
        "initial_capital": _text(request.initial_capital),
        "cost_model": request.cost_model.as_dict(),
        "criteria_thresholds": criteria_rules.normalize_thresholds(request.thresholds),
        "annualization_factor": _text(annualization_factor),
        "risk_free_rate": _text(request.risk_free_rate),
        "rebalance": request.rebalance,
        "price_basis": PRICE_BASIS,
        "data_source": DATA_SOURCE,
        "funding_assumption": FUNDING_ASSUMPTION,
    }


async def _ensure_data(
    session: AsyncSession,
    *,
    legs: Sequence[LegSpec],
    bar: str,
    windows: Sequence[Window],
) -> None:
    """窗口内任一腿没有任何已确认 bar 都必须失败，并列明缺口。"""

    gaps: list[dict[str, Any]] = []
    for window in windows:
        for leg in legs:
            count = await data.count_confirmed(
                session,
                instrument_id=leg.instrument_id,
                bar=bar,
                start=window.start,
                end=window.end,
            )
            if count == 0:
                gaps.append(
                    {
                        "instrument_id": leg.instrument_id,
                        "inst_id": leg.inst_id,
                        "window": {
                            "name": window.name,
                            "start": _iso(window.start),
                            "end": _iso(window.end),
                        },
                    }
                )
    if gaps:
        raise BacktestError(
            "insufficient_data",
            "no confirmed candles for part of the requested windows",
            details={"gaps": gaps},
        )


async def create(session: AsyncSession, request: BacktestRequest) -> tuple[BacktestRun, bool]:
    """登记回测；同 `run_key` 直接复用已有运行，不重复排队。"""

    settings = get_settings()
    if not request.rebalance == "none":
        raise BacktestError(
            "backtest_rebalance_unsupported",
            "P1 only supports rebalance=none (buy & hold)",
            details={"rebalance": request.rebalance},
        )
    source = await data.load_strategy_source(session, request.strategy_id)
    if source is None:
        raise BacktestError(
            "strategy_not_found",
            f"unknown strategy: {request.strategy_id}",
            status_code=404,
            details={"strategy_id": request.strategy_id},
        )
    if source.status != "approved":
        raise BacktestError(
            "strategy_not_approved",
            "only approved strategies can be backtested",
            status_code=409,
            details={"strategy_id": source.id, "status": source.status},
        )

    legs = await data.load_legs(session, source.id)
    if not legs:
        raise BacktestError(
            "strategy_no_legs",
            "strategy has no legs to backtest",
            status_code=422,
            details={"strategy_id": source.id},
        )

    try:
        bar = normalize_bar(request.bar)
    except ValueError as exc:
        raise BacktestError("backtest_invalid_bar", str(exc)) from exc
    windows = _normalize_windows(request)
    main_window, segments = windows
    all_windows = [main_window, *segments]
    _check_bar_and_span(bar, all_windows, settings)
    await _ensure_data(session, legs=legs, bar=bar, windows=all_windows)

    factor = request.annualization_factor or default_annualization_factor(bar)
    if factor <= 0:
        raise BacktestError("backtest_invalid_param", "annualization_factor must be positive")
    if request.initial_capital <= 0:
        raise BacktestError("backtest_invalid_capital", "initial_capital must be positive")

    normalized = _normalized_payload(
        request, source=source, windows=all_windows, bar=bar, annualization_factor=factor
    )
    run_key = digest(normalized)
    existing = await session.scalar(select(BacktestRun).where(BacktestRun.run_key == run_key))
    if existing is not None:
        return existing, False

    criteria_state = {
        "thresholds": normalized["criteria_thresholds"],
        "results": [],
        "passed": False,
        "default": not request.thresholds,
    }
    run = BacktestRun(
        run_key=run_key,
        strategy_id=source.id,
        strategy_version=source.version,
        window_start=main_window.start,
        window_end=main_window.end,
        bar=bar,
        initial_capital=request.initial_capital,
        cost_model=request.cost_model.as_dict(),
        params={**normalized, "criteria": criteria_state, "excluded_incomplete": {}},
        status="queued",
    )
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        # 并发提交同参数：另一个事务已抢先写入 run_key。回滚后按 run_key
        # 重查并复用已有运行，请求保持幂等而不是 500。
        await session.rollback()
        existing = await session.scalar(select(BacktestRun).where(BacktestRun.run_key == run_key))
        if existing is None:  # pragma: no cover - 冲突必然有行
            raise
        return existing, False
    await session.refresh(run)
    return run, True


def _cost_model_of(run: BacktestRun) -> CostModel:
    raw = dict(run.cost_model or {})
    return CostModel(
        taker_fee_bps=Decimal(str(raw.get("taker_fee_bps", "0"))),
        maker_fee_bps=Decimal(str(raw.get("maker_fee_bps", "0"))),
        slippage_bps=Decimal(str(raw.get("slippage_bps", "0"))),
        funding_bps_per_period=Decimal(str(raw.get("funding_bps_per_period", "0"))),
        funding_enabled=bool(raw.get("funding", True)),
        fee_role=str(raw.get("fee_role", "taker")),
    )


def windows_of(run: BacktestRun) -> list[Window]:
    params = run.params or {}
    return [
        Window(
            name=str(item["name"]),
            start=_aware(datetime.fromisoformat(str(item["start"]))),
            end=_aware(datetime.fromisoformat(str(item["end"]))),
            role=str(item.get("role", "eval")),
        )
        for item in params.get("windows", [])
    ]


def _metrics_for(
    simulation: Simulation,
    *,
    initial_capital: Decimal,
    annualization_factor: Decimal,
    risk_free_rate: Decimal,
) -> dict[str, Decimal]:
    return compute_metrics(
        equity=[point.equity for point in simulation.equity],
        initial_capital=initial_capital,
        net_pnls=list(simulation.net_pnls),
        traded_notional=simulation.traded_notional,
        total_fees=simulation.total_fees,
        total_funding=simulation.total_funding,
        total_slippage=simulation.total_slippage,
        annualization_factor=annualization_factor,
        risk_free_rate=risk_free_rate,
    )


async def _mark_failed(backtest_id: int, message: str) -> None:
    """用独立事务写 `failed` 终态：调用方 session 可能已因 flush 失败而失效。"""

    async with session_factory() as fresh:
        run = await fresh.get(BacktestRun, backtest_id)
        if run is None:  # pragma: no cover - 运行行已被删除
            return
        run.status = "failed"
        run.finished_at = datetime.now(tz=UTC)
        run.error = message
        await fresh.commit()


async def execute(session: AsyncSession, backtest_id: int) -> dict[str, Any]:
    """执行一次回测并把结果幂等写入；任何失败都把运行收敛为 `failed`。"""

    run = await session.get(BacktestRun, backtest_id)
    if run is None:
        raise BacktestError(
            "backtest_not_found", f"unknown backtest: {backtest_id}", status_code=404
        )

    try:
        run.status = "running"
        run.started_at = datetime.now(tz=UTC)
        run.error = None
        await session.commit()
        return await _run_once(session, run)
    except Exception as error:
        message = (
            f"{error.code}: {error.message}"
            if isinstance(error, BacktestError)
            else f"{type(error).__name__}: {error}"
        )
        # 当前事务可能已因 flush/commit 失败进入 aborted 状态：先回滚，
        # 再用独立事务写终态，避免二次异常把 run 永久留在 running。
        try:
            await session.rollback()
        except Exception:  # pragma: no cover - 连接已断开
            logger.exception("backtest %s rollback failed", backtest_id)
        try:
            await _mark_failed(backtest_id, message)
        except Exception:  # pragma: no cover - 数据库不可用
            logger.exception("backtest %s failed to persist failure", backtest_id)
        raise


async def _run_once(session: AsyncSession, run: BacktestRun) -> dict[str, Any]:
    params = run.params or {}
    cost_model = _cost_model_of(run)
    factor = Decimal(str(params.get("annualization_factor", "0")))
    if factor <= 0:
        factor = default_annualization_factor(run.bar)
    risk_free_rate = Decimal(str(params.get("risk_free_rate", "0")))
    legs = await data.load_legs(session, run.strategy_id)
    if not legs:
        raise BacktestError("strategy_no_legs", "strategy has no legs to backtest")
    windows = windows_of(run)
    if not windows:
        raise BacktestError("backtest_window_empty", "run has no windows")

    metrics: dict[str, Decimal] = {}
    excluded: dict[int, int] = {}
    main_simulation: Simulation | None = None
    for index, window in enumerate(windows):
        loaded = await data.load_bars(
            session,
            instrument_ids=[leg.instrument_id for leg in legs],
            bar=run.bar,
            start=window.start,
            end=window.end,
        )
        for instrument_id, count in loaded.excluded_incomplete.items():
            excluded[instrument_id] = excluded.get(instrument_id, 0) + count
        simulation = engine_mod.simulate(
            legs=legs,
            series=loaded.series,
            initial_capital=Decimal(run.initial_capital),
            cost_model=cost_model,
            window_start=window.start,
            window_end=window.end,
        )
        if index == 0:
            main_simulation = simulation
        suffix = "" if index == 0 else f"@{window.name}"
        window_metrics = _metrics_for(
            simulation,
            initial_capital=Decimal(run.initial_capital),
            annualization_factor=factor,
            risk_free_rate=risk_free_rate,
        )
        for name, value in window_metrics.items():
            metrics[f"{name}{suffix}"] = value

    assert main_simulation is not None
    criteria_params = params.get("criteria", {})
    criteria_state = criteria_rules.evaluate(
        {name: value for name, value in metrics.items() if "@" not in name},
        None if criteria_params.get("default") else criteria_params.get("thresholds"),
    )
    await _persist(
        session,
        run=run,
        simulation=main_simulation,
        metrics=metrics,
    )
    run.params = {
        **params,
        "criteria": criteria_state,
        "excluded_incomplete": {str(key): value for key, value in sorted(excluded.items())},
    }
    run.status = "ok"
    run.finished_at = datetime.now(tz=UTC)
    await session.commit()
    return {
        "status": "ok",
        "backtest_id": run.id,
        "run_key": run.run_key,
        "trades": len(main_simulation.trades),
        "criteria_passed": criteria_state["passed"],
    }


async def _persist(
    session: AsyncSession,
    *,
    run: BacktestRun,
    simulation: Simulation,
    metrics: Mapping[str, Decimal],
) -> None:
    """先删后插：重跑同一运行不会留下旧行，结果集始终是本次计算的完整快照。"""

    for model in (BacktestMetric, BacktestEquityPoint, BacktestTrade):
        await session.execute(delete(model).where(model.run_id == run.id))
    await session.execute(
        insert(BacktestMetric),
        [
            {
                "run_id": run.id,
                "name": name,
                "value": value,
                "unit": METRIC_UNITS.get(name.split("@", 1)[0], "ratio"),
            }
            for name, value in metrics.items()
        ],
    )
    await session.execute(
        insert(BacktestEquityPoint),
        [
            {
                "run_id": run.id,
                "ts": point.ts,
                "equity": point.equity,
                "cash": point.cash,
                "exposure": point.exposure,
                "drawdown": point.drawdown,
            }
            for point in simulation.equity
        ],
    )
    await session.execute(
        insert(BacktestTrade),
        [
            {
                "run_id": run.id,
                "instrument_id": trade.instrument_id,
                "side": trade.side,
                "entry_ts": trade.entry_ts,
                "exit_ts": trade.exit_ts,
                "entry_px": trade.entry_px,
                "exit_px": trade.exit_px,
                "qty": trade.qty,
                "gross_pnl": trade.gross_pnl,
                "fees": trade.fees,
                "funding": trade.funding,
                "slippage": trade.slippage,
                "net_pnl": trade.net_pnl,
                "bars_held": trade.bars_held,
                "exit_reason": trade.exit_reason,
            }
            for trade in simulation.trades
        ],
    )
    await session.commit()


async def mark_queued(session: AsyncSession, run: BacktestRun) -> None:
    """重试失败运行：把状态复位为排队，旧结果在下次执行时整体覆盖。"""

    run.status = "queued"
    run.error = None
    run.started_at = None
    run.finished_at = None
    await session.commit()


async def get_run(session: AsyncSession, backtest_id: int) -> BacktestRun:
    run = await session.get(BacktestRun, backtest_id)
    if run is None:
        raise BacktestError(
            "backtest_not_found", f"unknown backtest: {backtest_id}", status_code=404
        )
    return run


async def load_metrics(session: AsyncSession, backtest_id: int) -> list[BacktestMetric]:
    await get_run(session, backtest_id)
    return list(
        await session.scalars(
            select(BacktestMetric)
            .where(BacktestMetric.run_id == backtest_id)
            .order_by(BacktestMetric.name)
        )
    )


async def load_equity(
    session: AsyncSession,
    backtest_id: int,
    *,
    limit: int = 500,
    cursor: datetime | None = None,
) -> tuple[list[BacktestEquityPoint], datetime | None]:
    await get_run(session, backtest_id)
    statement = (
        select(BacktestEquityPoint)
        .where(BacktestEquityPoint.run_id == backtest_id)
        .order_by(BacktestEquityPoint.ts)
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(BacktestEquityPoint.ts > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].ts if len(rows) > limit else None
    return rows[:limit], next_cursor


async def load_trades(
    session: AsyncSession,
    backtest_id: int,
    *,
    limit: int = 200,
    cursor: int | None = None,
) -> tuple[list[BacktestTrade], int | None]:
    await get_run(session, backtest_id)
    statement = (
        select(BacktestTrade)
        .where(BacktestTrade.run_id == backtest_id)
        .order_by(BacktestTrade.id)
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(BacktestTrade.id > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


__all__ = [
    "RUN_KEY_VERSION",
    "BacktestRequest",
    "create",
    "digest",
    "execute",
    "get_run",
    "load_equity",
    "load_metrics",
    "load_trades",
    "mark_queued",
    "windows_of",
]
