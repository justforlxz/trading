"""执行编排：下单、订单同步、撤单、持仓与账户视图。

这里是 P3 唯一的下单入口：paper 与 real 走同一段生命周期代码，只在下单源
（`PrivateTradingSource`）上分叉。任何绕过本模块直接调用交易所的写法都会
让状态机、幂等与持仓归属失效。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.okx.private import OkxPrivateClient
from app.adapters.okx.rate_limit import UpstreamError, UpstreamUnavailable
from app.config import get_settings
from app.execution import data as execution_data
from app.execution import gate as execution_gate
from app.execution import models, paper
from app.execution.core import orders as order_core
from app.execution.core import positions as position_core
from app.execution.errors import ExecutionError
from app.ports.private import ExchangeFill, OrderRequest, PrivateTradingSource
from app.risk import service as risk_service
from app.risk.errors import RiskError

ZERO = Decimal("0")
MODE_PAPER = execution_gate.MODE_PAPER
MODE_REAL = execution_gate.MODE_REAL

_STATE_RANK = {
    "pending": 0,
    "submitted": 1,
    "partial": 2,
    "filled": 3,
    "canceled": 4,
    "rejected": 4,
}


def settings():
    return get_settings()


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def credentials_ready() -> bool:
    current = settings()
    return execution_gate.credentials_configured(
        api_key=current.okx_api_key,
        api_secret=current.okx_api_secret,
        passphrase=current.okx_api_passphrase,
    )


def authorized_strategy_ids() -> frozenset[int]:
    return execution_gate.parse_strategy_ids(settings().execution_real_strategy_ids)


def resolve_mode() -> str:
    return execution_gate.decide_mode(real_trading_enabled=settings().real_trading_enabled)


def mode_view() -> dict[str, Any]:
    """`GET /execution/mode` 的载荷；paper 时给出关闭真实交易的原因。"""

    current = settings()
    mode = resolve_mode()
    return {
        "mode": mode,
        "real_trading_enabled": current.real_trading_enabled,
        "credentials_configured": credentials_ready(),
        "real_strategy_ids": sorted(authorized_strategy_ids()),
        "paper_fill_chunks": [
            str(item) for item in paper.parse_chunks(current.execution_paper_fill_chunks)
        ],
        "stop_loss_ratio": str(current.execution_stop_loss_ratio),
        "reason": None if mode == MODE_REAL else execution_gate.CODE_REAL_DISABLED,
    }


def new_client_order_id() -> str:
    """OKX `clOrdId` 上限 32 字符，只允许字母数字。"""

    return f"t{uuid4().hex[:30]}"


def serialize_order(order: models.Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "client_order_id": order.client_order_id,
        "exchange_order_id": order.exchange_order_id,
        "mode": order.mode,
        "strategy_id": order.strategy_id,
        "instrument_id": order.instrument_id,
        "inst_id": order.inst_id,
        "side": order.side,
        "position_side": order.position_side,
        "order_type": order.order_type,
        "quantity": _text(order.quantity),
        "price": _text(order.price),
        "reduce_only": order.reduce_only,
        "intent": order.intent,
        "state": order.state,
        "filled_quantity": _text(order.filled_quantity),
        "average_price": _text(order.average_price),
        "fee": _text(order.fee),
        "reject_reason": order.reject_reason,
        "risk_event_id": order.risk_event_id,
        "created_at": _iso(order.created_at),
        "updated_at": _iso(order.updated_at),
        "submitted_at": _iso(order.submitted_at),
        "closed_at": _iso(order.closed_at),
    }


def serialize_fill(fill: models.Fill) -> dict[str, Any]:
    return {
        "id": fill.id,
        "order_id": fill.order_id,
        "fill_id": fill.fill_id,
        "strategy_id": fill.strategy_id,
        "instrument_id": fill.instrument_id,
        "inst_id": fill.inst_id,
        "side": fill.side,
        "position_side": fill.position_side,
        "quantity": _text(fill.quantity),
        "price": _text(fill.price),
        "fee": _text(fill.fee),
        "realized_pnl": _text(fill.realized_pnl),
        "filled_at": _iso(fill.filled_at),
    }


def serialize_valuation(item: position_core.PositionValuation) -> dict[str, Any]:
    unrealized = item.unrealized_pnl
    ratio = position_core.unrealized_ratio(item)
    return {
        "strategy_id": item.strategy_id,
        "instrument_id": item.instrument_id,
        "inst_id": item.inst_id,
        "position_side": item.position_side,
        "quantity": _text(item.quantity),
        "average_price": _text(item.average_price),
        "realized_pnl": _text(item.realized_pnl),
        "mark_price": _text(item.mark_price),
        "unrealized_pnl": _text(unrealized),
        "unrealized_ratio": _text(ratio),
        "notional": _text(item.notional),
    }


@asynccontextmanager
async def source_for(
    session: AsyncSession, mode: str, inst_id: str | None
) -> AsyncIterator[PrivateTradingSource]:
    """按下单模式取得交易源；real 模式的客户端用完即关。"""

    if mode == MODE_PAPER:
        yield paper.get_paper_source()
        return

    current = settings()
    inst_ids = [inst_id] if inst_id else []
    contract_sizes, lot_sizes = await execution_data.instrument_sizes(session, inst_ids)
    client = OkxPrivateClient(
        current.okx_rest_base_url,
        api_key=current.okx_api_key,
        api_secret=current.okx_api_secret,
        passphrase=current.okx_api_passphrase,
        contract_sizes=contract_sizes,
        lot_sizes=lot_sizes,
        timeout_seconds=current.okx_http_timeout_seconds,
        max_retries=current.okx_max_retries,
        backoff_seconds=current.okx_retry_backoff_seconds,
    )
    try:
        yield client
    finally:
        await client.aclose()


def _gate_check(*, mode: str, strategy_id: int | None, open_diffs: int) -> str:
    decision = execution_gate.check_submit(
        requested_mode=mode,
        real_trading_enabled=settings().real_trading_enabled,
        credentials_ready=credentials_ready(),
        strategy_id=strategy_id,
        authorized_strategy_ids=authorized_strategy_ids(),
        open_diffs=open_diffs,
    )
    if decision.rejected:
        raise ExecutionError(
            decision.code or "execution_rejected",
            decision.message,
            status_code=403,
            details={"mode": decision.mode},
        )
    return decision.mode


async def _risk_gate(session: AsyncSession, strategy_id: int) -> None:
    """入场单必须先拿到风控放行结论；任何异常都按拒绝处理（fail-closed）。"""

    try:
        result = await risk_service.evaluate(session, strategy_id=strategy_id, persist=False)
    except RiskError as exc:
        code = (
            "execution_strategy_not_approved"
            if exc.code == "strategy_not_approved"
            else "execution_risk_rejected"
        )
        raise ExecutionError(code, exc.message, status_code=409, details=exc.details) from exc
    if not result.get("allowed"):
        raise ExecutionError(
            "execution_risk_rejected",
            "风控未放行, 拒绝下单",
            status_code=409,
            details={
                "reason": result.get("reason"),
                "breaches": result.get("breaches", []),
            },
        )


async def load_by_client_order_id(
    session: AsyncSession, client_order_id: str
) -> models.Order | None:
    return (
        await session.execute(
            select(models.Order).where(models.Order.client_order_id == client_order_id)
        )
    ).scalar_one_or_none()


def same_payload(
    order: models.Order,
    *,
    strategy_id: int,
    inst_id: str,
    side: str,
    position_side: str,
    quantity: Decimal,
    order_type: str,
    price: Decimal | None,
    reduce_only: bool,
    intent: str,
) -> bool:
    """判断既有订单与本次请求是否描述同一笔单（幂等重放 vs 参数漂移）。"""

    return (
        order.strategy_id == strategy_id
        and order.inst_id == inst_id
        and order.side == side
        and order.position_side == position_side
        and order.quantity == quantity
        and order.order_type == order_type
        and order.price == price
        and order.reduce_only == reduce_only
        and order.intent == intent
    )


def ensure_same_payload(order: models.Order, **payload: Any) -> None:
    """同 `client_order_id` 但载荷不同：拒绝，不静默返回旧单。"""

    if not same_payload(order, **payload):
        raise ExecutionError(
            "execution_idempotency_conflict",
            "client_order_id 已存在且请求载荷不同",
            status_code=409,
            details={"client_order_id": order.client_order_id, "order_id": order.id},
        )


async def insert_order_once(session: AsyncSession, order: models.Order) -> bool:
    """写入订单；唯一约束冲突（并发同 key）返回 False 而不是抛 500。"""

    session.add(order)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def available_close_quantity(
    session: AsyncSession,
    *,
    strategy_id: int,
    instrument_id: int,
    position_side: str,
) -> Decimal:
    """该策略在该标的该方向上可平的数量（无持仓返回 0）。"""

    row = (
        await session.execute(
            select(models.Position).where(
                models.Position.strategy_id == strategy_id,
                models.Position.instrument_id == instrument_id,
                models.Position.position_side == position_side,
            )
        )
    ).scalar_one_or_none()
    return ZERO if row is None else row.quantity


async def submit_order(
    session: AsyncSession,
    *,
    strategy_id: int,
    inst_id: str,
    side: str,
    position_side: str,
    quantity: Decimal,
    order_type: str = "market",
    price: Decimal | None = None,
    reduce_only: bool = False,
    intent: str = "entry",
    client_order_id: str | None = None,
    mode: str | None = None,
    source: PrivateTradingSource | None = None,
) -> tuple[dict[str, Any], bool]:
    """提交一笔订单；返回 `(订单视图, 是否新建)`。

    `mode` 显式指定 paper / real（paper 端点固定传 paper）；缺省取全局模式。
    同一个 `client_order_id` 重复提交不会再次触达交易所，直接返回已有订单。
    """

    if side not in {"buy", "sell"}:
        raise ExecutionError("invalid_request", "side 必须是 buy 或 sell")
    if position_side not in {"long", "short"}:
        raise ExecutionError("invalid_request", "position_side 必须是 long 或 short")
    if order_type not in {"market", "limit"}:
        raise ExecutionError("invalid_request", "order_type 必须是 market 或 limit")
    if intent not in {"entry", "exit", "stop"}:
        raise ExecutionError("invalid_request", "intent 必须是 entry/exit/stop")
    if quantity <= ZERO:
        raise ExecutionError("invalid_request", "quantity 必须大于 0")
    if order_type == "limit" and (price is None or price <= ZERO):
        raise ExecutionError("invalid_request", "限价单必须给出正价格")

    key = client_order_id or new_client_order_id()
    payload = {
        "strategy_id": strategy_id,
        "inst_id": inst_id,
        "side": side,
        "position_side": position_side,
        "quantity": quantity,
        "order_type": order_type,
        "price": price,
        "reduce_only": reduce_only,
        "intent": intent,
    }
    # 幂等优先：同 key 重放直接返回既有单，不再过一次当前门禁/风控
    # （否则策略后来被撤销授权或风控收紧会把重放打成 409）。
    existing = await load_by_client_order_id(session, key)
    if existing is not None:
        ensure_same_payload(existing, **payload)
        return serialize_order(existing), False

    instrument = await execution_data.load_instrument(session, inst_id)
    if instrument is None:
        raise ExecutionError("not_found", f"标的 {inst_id} 不存在", status_code=404)
    strategy = await execution_data.load_strategy(session, strategy_id)
    if strategy is None:
        raise ExecutionError("not_found", f"策略 {strategy_id} 不存在", status_code=404)
    if strategy.status != "approved":
        raise ExecutionError(
            "execution_strategy_not_approved",
            "策略未通过审批, 不能下单",
            status_code=409,
            details={"status": strategy.status},
        )

    from app.execution import reconcile

    open_diffs = await reconcile.open_diff_count(session)
    requested_mode = mode or resolve_mode()
    mode = _gate_check(mode=requested_mode, strategy_id=strategy_id, open_diffs=open_diffs)

    if intent == "entry" and not reduce_only:
        await _risk_gate(session, strategy_id)

    if reduce_only:
        available = await available_close_quantity(
            session,
            strategy_id=strategy_id,
            instrument_id=instrument.id,
            position_side=position_side,
        )
        if quantity > available:
            raise ExecutionError(
                "execution_position_inconsistent",
                f"平仓数量 {_text(quantity)} 超过持仓 {_text(available)}",
                status_code=409,
                details={
                    "requested": _text(quantity),
                    "available": _text(available),
                    "inst_id": inst_id,
                    "position_side": position_side,
                },
            )

    order = models.Order(
        client_order_id=key,
        mode=mode,
        strategy_id=strategy_id,
        instrument_id=instrument.id,
        inst_id=inst_id,
        side=side,
        position_side=position_side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        reduce_only=reduce_only,
        intent=intent,
        state="pending",
        filled_quantity=ZERO,
        fee=ZERO,
    )
    if not await insert_order_once(session, order):
        # 并发同 key 提交：唯一约束兜底，回查既有单并按幂等契约返回。
        existing = await load_by_client_order_id(session, key)
        if existing is None:
            raise ExecutionError(
                "execution_idempotency_conflict",
                "同一 client_order_id 的并发提交未能收敛",
                status_code=409,
                details={"client_order_id": key},
            )
        ensure_same_payload(existing, **payload)
        return serialize_order(existing), False

    request = OrderRequest(
        inst_id=inst_id,
        side=side,
        position_side=position_side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        client_order_id=key,
        reduce_only=reduce_only,
    )

    async def _run(active: PrivateTradingSource) -> None:
        try:
            ack = await active.place_order(request)
        except UpstreamUnavailable as exc:
            # 请求可能已到达交易所：保留 pending，交给恢复流程判定，绝不猜测。
            raise ExecutionError(
                "execution_upstream_unavailable",
                "交易所不可用, 订单状态待恢复流程确认",
                status_code=503,
                details={"client_order_id": key, "reason": str(exc)},
            ) from exc
        except (UpstreamError, ValueError) as exc:
            order.state = order_core.ensure_transition(order.state, "rejected")
            order.reject_reason = str(exc)
            order.closed_at = datetime.now(tz=UTC)
            await session.commit()
            raise ExecutionError(
                "execution_upstream_rejected",
                "交易所拒绝订单",
                status_code=502,
                details={"client_order_id": key, "reason": str(exc)},
            ) from exc
        order.exchange_order_id = ack.exchange_order_id
        order.state = order_core.ensure_transition(order.state, "submitted")
        order.submitted_at = datetime.now(tz=UTC)
        await session.commit()
        await sync_order(session, order, active)

    if source is not None:
        await _run(source)
    else:
        async with source_for(session, mode, inst_id) as active:
            await _run(active)
    return serialize_order(order), True


async def _apply_fill(session: AsyncSession, order: models.Order, fill: ExchangeFill) -> bool:
    """把一笔成交幂等落库并更新策略持仓；已记账的成交返回 False。"""

    existing = (
        await session.execute(
            select(models.Fill).where(
                models.Fill.order_id == order.id, models.Fill.fill_id == fill.fill_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    realized_delta = ZERO
    if order.strategy_id is not None:
        position = (
            await session.execute(
                select(models.Position).where(
                    models.Position.strategy_id == order.strategy_id,
                    models.Position.instrument_id == order.instrument_id,
                    models.Position.position_side == order.position_side,
                )
            )
        ).scalar_one_or_none()
        before = position_core.empty(order.position_side)
        if position is not None:
            before = position_core.PositionSnapshot(
                position_side=position.position_side,
                quantity=position.quantity,
                average_price=position.average_price,
                realized_pnl=position.realized_pnl,
            )
        try:
            after = position_core.apply_fill(
                before,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
            )
        except position_core.PositionError as exc:
            raise ExecutionError(
                "execution_position_inconsistent", str(exc), status_code=409
            ) from exc
        realized_delta = after.realized_pnl - before.realized_pnl
        if position is None:
            session.add(
                models.Position(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    inst_id=order.inst_id,
                    position_side=after.position_side,
                    quantity=after.quantity,
                    average_price=after.average_price,
                    realized_pnl=after.realized_pnl,
                )
            )
        else:
            position.quantity = after.quantity
            position.average_price = after.average_price
            position.realized_pnl = after.realized_pnl

    session.add(
        models.Fill(
            order_id=order.id,
            fill_id=fill.fill_id,
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            inst_id=order.inst_id,
            side=fill.side,
            position_side=order.position_side,
            quantity=fill.quantity,
            price=fill.price,
            fee=fill.fee,
            realized_pnl=realized_delta,
            filled_at=fill.filled_at,
        )
    )

    if order.state == "pending":
        order.state = order_core.ensure_transition(order.state, "submitted")
    snapshot = order_core.OrderSnapshot(
        state=order.state,
        quantity=order.quantity,
        filled_quantity=order.filled_quantity,
        average_price=order.average_price or ZERO,
        fee=order.fee,
    )
    try:
        updated = order_core.apply_fill(
            snapshot, quantity=fill.quantity, price=fill.price, fee=fill.fee
        )
    except order_core.OrderStateError as exc:
        raise ExecutionError("execution_invalid_transition", str(exc), status_code=409) from exc
    order.state = updated.state
    order.filled_quantity = updated.filled_quantity
    order.average_price = updated.average_price
    order.fee = updated.fee
    return True


async def _advance_state(session: AsyncSession, order: models.Order, snapshot: Any) -> None:
    """把订单状态推进到交易所快照的状态；只前进，不回退。"""

    try:
        target = order_core.normalize_exchange_state(snapshot.state)
    except order_core.OrderStateError:
        return
    if _STATE_RANK.get(target, 0) <= _STATE_RANK.get(order.state, 0):
        return
    if order_core.can_transition(order.state, target):
        order.state = target
        if target in order_core.TERMINAL_STATES and order.closed_at is None:
            order.closed_at = datetime.now(tz=UTC)


def _terminate_after_apply_failure(order: models.Order, error: ExecutionError) -> None:
    """成交无法落到本地账本时，订单必须收敛到终态。

    停在 `submitted` 会让对账/恢复每次重试都再撞一次同一笔非法成交，
    形成跨重启的 500；`pending`/`submitted` 记 `rejected`，已有部分成交记 `canceled`。
    """

    order.reject_reason = error.message
    if order.state in order_core.TERMINAL_STATES:
        return
    target = "rejected" if order.state in {"pending", "submitted"} else "canceled"
    order.state = target if order_core.can_transition(order.state, target) else "canceled"
    if order.closed_at is None:
        order.closed_at = datetime.now(tz=UTC)


async def sync_order(
    session: AsyncSession, order: models.Order, source: PrivateTradingSource
) -> models.Order:
    """拉取交易所订单与成交，幂等落库并推进状态机。"""

    snapshot = await source.fetch_order(
        inst_id=order.inst_id,
        client_order_id=order.client_order_id,
        exchange_order_id=order.exchange_order_id,
    )
    if snapshot is None:
        return order

    fills = await source.fetch_fills(inst_id=order.inst_id, since=order.submitted_at)
    matched = 0
    try:
        for fill in fills:
            if (
                fill.client_order_id != order.client_order_id
                and fill.exchange_order_id != order.exchange_order_id
            ):
                continue
            matched += 1
            await _apply_fill(session, order, fill)
    except ExecutionError as error:
        _terminate_after_apply_failure(order, error)
        await session.commit()
        raise

    if matched == 0 and snapshot.filled_quantity > order.filled_quantity:
        # 成交明细缺失时用交易所订单快照补记（accFillSz/avgPx 是交易所事实，不是估算）。
        synthetic = ExchangeFill(
            fill_id=f"ord-{snapshot.exchange_order_id}",
            client_order_id=order.client_order_id,
            exchange_order_id=snapshot.exchange_order_id,
            inst_id=order.inst_id,
            side=order.side,
            position_side=order.position_side,
            quantity=snapshot.filled_quantity - order.filled_quantity,
            price=snapshot.average_price,
            fee=ZERO,
            fee_currency="USDT",
            filled_at=datetime.now(tz=UTC),
        )
        try:
            await _apply_fill(session, order, synthetic)
        except ExecutionError as error:
            _terminate_after_apply_failure(order, error)
            await session.commit()
            raise

    await _advance_state(session, order, snapshot)
    await session.commit()
    return order


async def poll_order(
    session: AsyncSession, order_id: int, *, source: PrivateTradingSource | None = None
) -> dict[str, Any]:
    order = await session.get(models.Order, order_id)
    if order is None:
        raise ExecutionError("not_found", f"订单 {order_id} 不存在", status_code=404)
    if source is not None:
        await sync_order(session, order, source)
    else:
        async with source_for(session, order.mode, order.inst_id) as active:
            await sync_order(session, order, active)
    return serialize_order(order)


async def cancel_order(
    session: AsyncSession, order_id: int, *, source: PrivateTradingSource | None = None
) -> dict[str, Any]:
    order = await session.get(models.Order, order_id)
    if order is None:
        raise ExecutionError("not_found", f"订单 {order_id} 不存在", status_code=404)
    if order.state in order_core.TERMINAL_STATES:
        return serialize_order(order)

    async def _run(active: PrivateTradingSource) -> None:
        await active.cancel_order(
            inst_id=order.inst_id,
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
        )
        await sync_order(session, order, active)
        if order.state in {"submitted", "partial"}:
            order.state = order_core.ensure_transition(order.state, "canceled")
            order.closed_at = datetime.now(tz=UTC)
            order.reject_reason = "canceled_by_user"
            await session.commit()

    if source is not None:
        await _run(source)
    else:
        async with source_for(session, order.mode, order.inst_id) as active:
            await _run(active)
    return serialize_order(order)


async def list_orders(
    session: AsyncSession,
    *,
    strategy_id: int | None = None,
    state: str | None = None,
    mode: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    statement = select(models.Order).order_by(models.Order.id.desc()).limit(limit + 1)
    if strategy_id is not None:
        statement = statement.where(models.Order.strategy_id == strategy_id)
    if state is not None:
        statement = statement.where(models.Order.state == state)
    if mode is not None:
        statement = statement.where(models.Order.mode == mode)
    if cursor is not None:
        statement = statement.where(models.Order.id < cursor)
    rows = list((await session.execute(statement)).scalars())
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return {
        "items": [serialize_order(row) for row in rows[:limit]],
        "next_cursor": next_cursor,
    }


async def order_view(session: AsyncSession, order_id: int) -> dict[str, Any]:
    order = await session.get(models.Order, order_id)
    if order is None:
        raise ExecutionError("not_found", f"订单 {order_id} 不存在", status_code=404)
    fills = list(
        (
            await session.execute(
                select(models.Fill).where(models.Fill.order_id == order.id).order_by(models.Fill.id)
            )
        ).scalars()
    )
    body = serialize_order(order)
    body["fills"] = [serialize_fill(fill) for fill in fills]
    return body


async def position_valuations(
    session: AsyncSession, *, strategy_id: int | None = None
) -> list[position_core.PositionValuation]:
    """当前持仓（数量 > 0）及其标记价格估值。"""

    statement = select(models.Position).where(models.Position.quantity > 0)
    if strategy_id is not None:
        statement = statement.where(models.Position.strategy_id == strategy_id)
    rows = list((await session.execute(statement.order_by(models.Position.id))).scalars())
    instrument_ids = sorted({row.instrument_id for row in rows})
    marks = await execution_data.latest_closes(
        session, instrument_ids, bar=settings().execution_quote_bar
    )
    inputs = [
        position_core.PositionRow(
            strategy_id=row.strategy_id,
            instrument_id=row.instrument_id,
            inst_id=row.inst_id,
            position_side=row.position_side,
            quantity=row.quantity,
            average_price=row.average_price,
            realized_pnl=row.realized_pnl,
        )
        for row in rows
    ]
    marks_by_side = {
        (row.instrument_id, row.position_side): marks[row.instrument_id]
        for row in rows
        if row.instrument_id in marks
    }
    return position_core.mark_to_market(inputs, marks_by_side)


async def positions_view(
    session: AsyncSession, *, strategy_id: int | None = None
) -> dict[str, Any]:
    """持仓列表 + 账户合计；数值一律字符串（api-contract §1）。"""

    valuations = await position_valuations(session, strategy_id=strategy_id)
    totals = position_core.account_totals(valuations)
    return {
        "items": [serialize_valuation(item) for item in valuations],
        "totals": {
            "realized_pnl": _text(totals.realized_pnl),
            "unrealized_pnl": _text(totals.unrealized_pnl),
            "total_pnl": _text(totals.total_pnl),
            "gross_notional": _text(totals.gross_notional),
            "net_notional": _text(totals.net_notional),
            "positions": totals.positions,
        },
    }


async def account_view(session: AsyncSession) -> dict[str, Any]:
    from app.execution import reconcile

    view = await positions_view(session)
    return {
        "mode": resolve_mode(),
        "totals": view["totals"],
        "open_diffs": await reconcile.open_diff_count(session),
    }


__all__ = [
    "MODE_PAPER",
    "MODE_REAL",
    "account_view",
    "available_close_quantity",
    "cancel_order",
    "credentials_ready",
    "list_orders",
    "mode_view",
    "new_client_order_id",
    "order_view",
    "poll_order",
    "position_valuations",
    "positions_view",
    "resolve_mode",
    "serialize_fill",
    "serialize_order",
    "serialize_valuation",
    "submit_order",
    "sync_order",
]
