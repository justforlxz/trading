"""paper 撮合器：实现 `PrivateTradingSource` 的本地模拟交易所。

刻意保留真实市场的两件事：

* **部分成交**：成交按 `EXECUTION_PAPER_FILL_CHUNKS` 的比例分段，每次轮询消耗一段，
  默认 `0.5,0.5`，因此 paper 市价单第一次轮询是 `partial`、第二次才是 `filled`。
* **订单状态**：与实盘共用 `execution.core.orders` 的状态机，模拟器不另立状态。

paper 的持仓/账户由本地成交推导，进程重启后模拟交易所状态丢失——这正是
`execution.recovery` 存在的场景：本地未完成订单会被重新接管或安全撤销。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.config import get_settings
from app.execution.core import positions as position_core
from app.ports.private import (
    AccountBalance,
    ExchangeFill,
    ExchangeOrder,
    ExchangePosition,
    OrderAck,
    OrderRequest,
)

ZERO = Decimal("0")


def parse_chunks(raw: str | None) -> tuple[Decimal, ...]:
    """解析成交比例；非法或越界片段丢弃，全空时退化为一次性全额成交。"""

    chunks: list[Decimal] = []
    for part in (raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        try:
            value = Decimal(text)
        except ArithmeticError:
            continue
        if ZERO < value <= Decimal("1"):
            chunks.append(value)
    return tuple(chunks) or (Decimal("1"),)


@dataclass(slots=True)
class _PaperOrder:
    request: OrderRequest
    price: Decimal
    filled: Decimal = ZERO
    fills: list[ExchangeFill] = field(default_factory=list)
    canceled: bool = False
    next_chunk: int = 0

    @property
    def state(self) -> str:
        if self.canceled:
            return "canceled"
        if self.filled >= self.request.quantity:
            return "filled"
        if self.filled > ZERO:
            return "partial"
        return "submitted"

    def snapshot(self) -> ExchangeOrder:
        average = (
            sum((item.price * item.quantity for item in self.fills), ZERO) / self.filled
            if self.filled > ZERO
            else ZERO
        )
        fee = sum((item.fee for item in self.fills), ZERO)
        return ExchangeOrder(
            client_order_id=self.request.client_order_id,
            exchange_order_id=f"paper-{self.request.client_order_id}",
            inst_id=self.request.inst_id,
            side=self.request.side,
            position_side=self.request.position_side,
            state=self.state,
            quantity=self.request.quantity,
            filled_quantity=self.filled,
            average_price=average,
            fee=fee,
            updated_at=datetime.now(tz=UTC),
        )


class PaperTradingSource:
    """确定性 paper 撮合器；成交价取订单限价或最近确认 K 线收盘价。"""

    def __init__(
        self,
        *,
        quote_provider,
        chunks: tuple[Decimal, ...] = (Decimal("1"),),
        clock=None,
    ) -> None:
        self._quote_provider = quote_provider
        self._chunks = chunks
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._orders: dict[str, _PaperOrder] = {}

    def reset(self) -> None:
        self._orders.clear()

    def rehydrate(
        self,
        entries: list[tuple[OrderRequest, Decimal, str, list[ExchangeFill]]],
    ) -> None:
        """用持久化的订单/成交重建模拟交易所状态（进程重启后的接管）。

        paper 的「交易所状态」本来就只有本地成交这一份事实，重建不是补造数据。
        """

        for request, price, state, fills in entries:
            self._orders[request.client_order_id] = _PaperOrder(
                request=request,
                price=price,
                filled=sum((item.quantity for item in fills), ZERO),
                fills=list(fills),
                canceled=state in {"canceled", "rejected"},
            )

    async def place_order(self, request: OrderRequest) -> OrderAck:
        price = request.price
        if price is None:
            price = await self._quote_provider(request.inst_id)
        if price is None or price <= ZERO:
            raise ValueError(f"no paper quote for {request.inst_id}")
        self._orders[request.client_order_id] = _PaperOrder(request=request, price=price)
        return OrderAck(
            client_order_id=request.client_order_id,
            exchange_order_id=f"paper-{request.client_order_id}",
            state="submitted",
            code="0",
        )

    def _advance(self, paper_order: _PaperOrder) -> None:
        if paper_order.canceled or paper_order.filled >= paper_order.request.quantity:
            return
        # 没有有效价格的僵尸单不撮合：0 价成交会污染持仓账本。
        if paper_order.price is None or paper_order.price <= ZERO:
            return
        ratio = self._chunks[paper_order.next_chunk % len(self._chunks)]
        paper_order.next_chunk += 1
        remaining = paper_order.request.quantity - paper_order.filled
        quantity = min(remaining, paper_order.request.quantity * ratio)
        if quantity <= ZERO:
            quantity = remaining
        if paper_order.request.reduce_only:
            # 模拟交易所的 reduce-only 语义：最多平掉当前持仓，绝不反向开仓。
            quantity = min(
                quantity,
                self._position_quantity(
                    paper_order.request.inst_id, paper_order.request.position_side
                ),
            )
            if quantity <= ZERO:
                return
        fill = ExchangeFill(
            fill_id=f"{paper_order.request.client_order_id}-{len(paper_order.fills) + 1}",
            client_order_id=paper_order.request.client_order_id,
            exchange_order_id=f"paper-{paper_order.request.client_order_id}",
            inst_id=paper_order.request.inst_id,
            side=paper_order.request.side,
            position_side=paper_order.request.position_side,
            quantity=quantity,
            price=paper_order.price,
            fee=ZERO,
            fee_currency="USDT",
            filled_at=self._clock(),
        )
        paper_order.fills.append(fill)
        paper_order.filled += quantity

    def _position_quantity(self, inst_id: str, position_side: str) -> Decimal:
        """按已成交记录推导当前持仓数量；非法历史成交跳过，不阻断模拟撮合。"""

        snapshot = position_core.empty(position_side)
        for paper_order in self._orders.values():
            for fill in paper_order.fills:
                if fill.inst_id != inst_id or fill.position_side != position_side:
                    continue
                try:
                    snapshot = position_core.apply_fill(
                        snapshot,
                        side=fill.side,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                    )
                except position_core.PositionError:
                    continue
        return snapshot.quantity

    async def cancel_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> None:
        key = client_order_id or (exchange_order_id or "").removeprefix("paper-")
        paper_order = self._orders.get(key)
        if paper_order is None:
            raise ValueError(f"unknown paper order: {key}")
        paper_order.canceled = True

    async def fetch_order(
        self,
        *,
        inst_id: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> ExchangeOrder | None:
        key = client_order_id or (exchange_order_id or "").removeprefix("paper-")
        paper_order = self._orders.get(key)
        if paper_order is None:
            return None
        self._advance(paper_order)
        return paper_order.snapshot()

    async def list_open_orders(self, *, inst_id: str | None = None) -> list[ExchangeOrder]:
        result: list[ExchangeOrder] = []
        for paper_order in self._orders.values():
            if paper_order.state in {"submitted", "partial"} and (
                inst_id is None or paper_order.request.inst_id == inst_id
            ):
                result.append(paper_order.snapshot())
        return result

    async def fetch_fills(
        self, *, inst_id: str | None = None, since: datetime | None = None
    ) -> list[ExchangeFill]:
        result: list[ExchangeFill] = []
        for paper_order in self._orders.values():
            for fill in paper_order.fills:
                if inst_id is not None and fill.inst_id != inst_id:
                    continue
                if since is not None and fill.filled_at < since:
                    continue
                result.append(fill)
        return result

    async def fetch_positions(self) -> list[ExchangePosition]:
        snapshots: dict[tuple[str, str], position_core.PositionSnapshot] = {}
        for paper_order in self._orders.values():
            for fill in paper_order.fills:
                key = (fill.inst_id, fill.position_side)
                current = snapshots.get(key) or position_core.empty(fill.position_side)
                try:
                    snapshots[key] = position_core.apply_fill(
                        current,
                        side=fill.side,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                    )
                except position_core.PositionError:
                    # 不可能成交（例如超量平仓的历史残留）不计入模拟持仓，
                    # 让对账以「本地 vs 交易所」差异暴露，而不是 500。
                    continue
        return [
            ExchangePosition(
                inst_id=inst_id,
                position_side=position_side,
                quantity=snapshot.quantity,
                average_price=snapshot.average_price,
                unrealized_pnl=ZERO,
            )
            for (inst_id, position_side), snapshot in snapshots.items()
            if snapshot.quantity > ZERO
        ]

    async def fetch_balance(self) -> AccountBalance:
        realized = sum((item.realized_pnl for item in self._realized()), ZERO)
        return AccountBalance(total_equity=realized, available_equity=realized, currency="USDT")

    def _realized(self) -> list[position_core.PositionSnapshot]:
        snapshots: dict[tuple[str, str], position_core.PositionSnapshot] = {}
        for paper_order in self._orders.values():
            for fill in paper_order.fills:
                key = (fill.inst_id, fill.position_side)
                current = snapshots.get(key) or position_core.empty(fill.position_side)
                try:
                    snapshots[key] = position_core.apply_fill(
                        current,
                        side=fill.side,
                        quantity=fill.quantity,
                        price=fill.price,
                        fee=fill.fee,
                    )
                except position_core.PositionError:
                    # 不可能成交（例如超量平仓的历史残留）不计入模拟持仓，
                    # 让对账以「本地 vs 交易所」差异暴露，而不是 500。
                    continue
        return list(snapshots.values())


async def _default_quote(inst_id: str) -> Decimal | None:
    """默认报价：最近一根确认 K 线的收盘价（每次新开会话，不持有请求会话）。"""

    from app.db import session as db_session
    from app.execution import data as execution_data

    async with db_session.session_factory() as session:
        instrument = await execution_data.load_instrument(session, inst_id)
        if instrument is None:
            return None
        return await execution_data.latest_close(
            session, instrument.id, bar=get_settings().execution_quote_bar
        )


_paper_source: PaperTradingSource | None = None


def get_paper_source() -> PaperTradingSource:
    """进程级 paper 模拟器；同一进程内多请求共享撮合状态。"""

    global _paper_source
    if _paper_source is None:
        settings = get_settings()
        _paper_source = PaperTradingSource(
            quote_provider=_default_quote,
            chunks=parse_chunks(settings.execution_paper_fill_chunks),
            clock=lambda: datetime.now(tz=UTC),
        )
    return _paper_source


def reset_paper_source() -> None:
    """测试与验收脚本用：清空进程内模拟撮合状态。"""

    global _paper_source
    _paper_source = None


__all__ = [
    "PaperTradingSource",
    "get_paper_source",
    "parse_chunks",
    "reset_paper_source",
]
