"""下单意图的本地登记：`clientOrderId` 幂等键落库。

为什么必须在**发请求之前**落库：下游订单号来自上游应答，断电或进程被杀时拿不到。
先登记意图，重启后才知道「这个 `clientOrderId` 可能已经发出去了」，于是先去上游
查这张单，而不是盲目重发。顺序反过来的话，两次进程都可能在对方落库之前发出去，
上游就会出现两张单。

`status` 只有三个取值，含义是「本地知道的事实」，不是订单状态机的状态：

- `recorded`：已登记，还不知道上游有没有收到。
- `submitted`：上游确认了，`order_id` 就是上游订单号。
- `rejected`：上游明确拒单，这张单不存在；同一个 `clientOrderId` 可以再次尝试。

上游的订单状态（`live` / `partially_filled` / `filled` / `canceled`）由执行层的状态
机维护，不写进这张表——这里只回答「这个幂等键有没有对应的单」。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from app.core import OrderIntent
from app.db import Base, DecimalText, UtcDateTime, session_scope

__all__ = [
    "STATUS_RECORDED",
    "STATUS_REJECTED",
    "STATUS_SUBMITTED",
    "OrderSubmission",
    "claim_submission",
    "load_submission",
    "mark_rejected",
    "mark_submitted",
    "reopen_submission",
]

#: 已登记，上游是否收到未知。
STATUS_RECORDED = "recorded"
#: 上游已确认，`order_id` 有值。
STATUS_SUBMITTED = "submitted"
#: 上游明确拒单，这张单不存在。
STATUS_REJECTED = "rejected"

_STATUS_MAX = 16
_ID_MAX = 64
_SIDE_MAX = 8
_ORDER_TYPE_MAX = 16


class OrderSubmission(Base):
    """一行 = 一个 `clientOrderId` 的登记记录（主键就是幂等键）。"""

    __tablename__ = "order_submissions"

    client_order_id: Mapped[str] = mapped_column(String(_ID_MAX), primary_key=True)
    inst_id: Mapped[str] = mapped_column(String(_ID_MAX), nullable=False)
    side: Mapped[str] = mapped_column(String(_SIDE_MAX), nullable=False)
    order_type: Mapped[str] = mapped_column(String(_ORDER_TYPE_MAX), nullable=False)
    qty: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(_ID_MAX), nullable=True)
    status: Mapped[str] = mapped_column(String(_STATUS_MAX), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


def claim_submission(intent: OrderIntent, *, now: datetime) -> bool:
    """登记一个下单意图并立即提交；返回 `True` 表示本次是首次登记。

    依赖主键冲突判重，所以并发提交同一个 `clientOrderId` 时只有一个调用方拿到
    `True`：数据库就是那把锁，不需要进程内的锁也不需要先查后写。

    判「插进去了没有」只能用 `RETURNING`：`INSERT … ON CONFLICT DO NOTHING` 经
    SQLAlchemy 执行后 `rowcount` 是 `-1`（不是 0/1），拿它比较会恒为假，于是首次登记
    也被当成「已存在」，白白多打一次上游查单。
    """

    if not intent.client_order_id:
        raise ValueError("登记下单意图必须给出 client_order_id")
    statement = (
        insert(OrderSubmission)
        .values(
            client_order_id=intent.client_order_id,
            inst_id=intent.inst_id,
            side=intent.side,
            order_type=intent.order_type,
            qty=intent.qty,
            price=intent.price,
            order_id=None,
            status=STATUS_RECORDED,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[OrderSubmission.client_order_id])
        .returning(OrderSubmission.client_order_id)
    )
    with session_scope() as session:
        return session.execute(statement).scalar_one_or_none() is not None


def load_submission(client_order_id: str) -> OrderSubmission | None:
    """按幂等键读出登记记录；没有登记过返回 `None`。"""

    with session_scope() as session:
        return session.get(OrderSubmission, client_order_id)


def mark_submitted(client_order_id: str, order_id: str, *, now: datetime) -> None:
    """上游确认收到：记下订单号，状态推进到 `submitted`。"""

    with session_scope() as session:
        row = session.get(OrderSubmission, client_order_id)
        if row is None:
            raise ValueError(f"未登记的下单意图:{client_order_id}")
        row.order_id = order_id
        row.status = STATUS_SUBMITTED
        row.updated_at = now


def mark_rejected(client_order_id: str, *, now: datetime) -> None:
    """上游明确拒单：这张单不存在，但幂等键仍然留着（重试时走同一个键）。"""

    with session_scope() as session:
        row = session.get(OrderSubmission, client_order_id)
        if row is None:
            raise ValueError(f"未登记的下单意图:{client_order_id}")
        row.status = STATUS_REJECTED
        row.updated_at = now


def reopen_submission(client_order_id: str, *, now: datetime) -> None:
    """回到 `recorded`：用于「上游查不到这张单」，允许同一个幂等键重发。"""

    with session_scope() as session:
        row = session.get(OrderSubmission, client_order_id)
        if row is None:
            raise ValueError(f"未登记的下单意图:{client_order_id}")
        row.order_id = None
        row.status = STATUS_RECORDED
        row.updated_at = now
