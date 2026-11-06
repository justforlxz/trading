"""目标股票 CRUD（P1-06）。

- `exchange` 必填且限定 `XNAS`/`XNYS`/`NYSE_ARCA`：目标是用户显式添加的股票，
  不用 NULL 表示未知交易所；
- `(symbol, exchange)` 唯一，重复添加返回已存在记录（不产生副本）；
- 删除是软删除（`enabled=false`），行仍在库中，保证历史关系快照的外键不悬空。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import Instrument
from app.research.models import TargetSymbol

EXCHANGES: tuple[str, ...] = ("XNAS", "XNYS", "NYSE_ARCA")

_UNSET = object()


@dataclass(frozen=True, slots=True)
class CreateResult:
    target: TargetSymbol
    created: bool


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


async def resolve_instrument_id(session: AsyncSession, symbol: str) -> int | None:
    """按 `market.instrument.uly` 的首段匹配合约；没有对应合约时返回 `None`。

    目标股票允许暂时没有可交易合约（例如仅用于分析），因此这里不是错误路径。
    """

    statement = (
        select(Instrument.id)
        .where(func.split_part(Instrument.uly, "-", 1) == symbol)
        .order_by(Instrument.id)
        .limit(1)
    )
    return await session.scalar(statement)


async def create_target(
    session: AsyncSession,
    *,
    symbol: str,
    exchange: str,
    display_name: str | None = None,
    note: str | None = None,
) -> CreateResult:
    """幂等创建：冲突时返回已存在的那一行（`created=False`）。"""

    normalized = normalize_symbol(symbol)
    values = {
        "symbol": normalized,
        "exchange": exchange,
        "display_name": display_name,
        "note": note,
        "instrument_id": await resolve_instrument_id(session, normalized),
    }
    statement = (
        pg_insert(TargetSymbol)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["symbol", "exchange"])
        .returning(TargetSymbol.id)
    )
    inserted_id = await session.scalar(statement)
    if inserted_id is None:
        existing = await session.scalar(
            select(TargetSymbol).where(
                TargetSymbol.symbol == normalized, TargetSymbol.exchange == exchange
            )
        )
        assert existing is not None
        await session.commit()
        return CreateResult(target=existing, created=False)
    await session.commit()
    created = await session.get(TargetSymbol, inserted_id)
    assert created is not None
    return CreateResult(target=created, created=True)


async def get_target(session: AsyncSession, target_id: int) -> TargetSymbol | None:
    return await session.get(TargetSymbol, target_id)


async def list_targets(
    session: AsyncSession,
    *,
    enabled: bool | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> tuple[list[TargetSymbol], int | None]:
    """按创建顺序（id 升序）分页；`enabled=None` 不过滤，`cursor` 为上一页最后一条的 id。"""

    statement = select(TargetSymbol).order_by(TargetSymbol.id).limit(limit + 1)
    if enabled is not None:
        statement = statement.where(TargetSymbol.enabled.is_(enabled))
    if cursor is not None:
        statement = statement.where(TargetSymbol.id > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


async def update_target(
    session: AsyncSession,
    target: TargetSymbol,
    *,
    display_name: str | object | None = _UNSET,
    note: str | object | None = _UNSET,
) -> TargetSymbol:
    if display_name is not _UNSET:
        target.display_name = display_name  # type: ignore[assignment]
    if note is not _UNSET:
        target.note = note  # type: ignore[assignment]
    await session.commit()
    await session.refresh(target)
    return target


async def soft_delete_target(session: AsyncSession, target: TargetSymbol) -> TargetSymbol:
    target.enabled = False
    await session.commit()
    await session.refresh(target)
    return target


__all__ = [
    "EXCHANGES",
    "CreateResult",
    "create_target",
    "get_target",
    "list_targets",
    "normalize_symbol",
    "resolve_instrument_id",
    "soft_delete_target",
    "update_target",
]
