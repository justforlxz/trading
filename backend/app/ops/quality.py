"""数据质量：问题登记（幂等）、跳变检测、陈旧检测与查询。

去重键固定为 `(dataset, scope_id, kind, window_start)`：同一缺口反复检测只更新
`last_seen_at`，不会产生重复行（`docs/architecture/data-model.md` §3.7）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.models import DataQualityIssue
from app.ports.market_data import CandleRow

ISSUE_KINDS: tuple[str, ...] = (
    "GAP",
    "DUPLICATE",
    "OUTLIER",
    "STALE",
    "UNCONFIRMED",
    "MISSING_SOURCE",
)

SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")


@dataclass(frozen=True, slots=True)
class Outlier:
    """相邻两根 K 线的收盘价跳变。"""

    open_time: datetime
    previous_close: Decimal
    close: Decimal
    ratio: float


async def record_issue(
    session: AsyncSession,
    *,
    dataset: str,
    scope_id: str,
    kind: str,
    window_start: datetime,
    window_end: datetime | None = None,
    severity: str = "warning",
    detail: dict[str, Any] | None = None,
) -> None:
    """登记或刷新一条数据质量问题（幂等）。"""

    if kind not in ISSUE_KINDS:
        raise ValueError(f"unknown issue kind: {kind}")
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity: {severity}")
    now = datetime.now(tz=UTC)
    statement = pg_insert(DataQualityIssue).values(
        dataset=dataset,
        scope_id=scope_id,
        kind=kind,
        severity=severity,
        window_start=window_start,
        window_end=window_end,
        detail=detail or {},
        detected_at=now,
        last_seen_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_data_quality_issue",
        set_={
            "window_end": statement.excluded.window_end,
            "severity": statement.excluded.severity,
            "detail": statement.excluded.detail,
            "last_seen_at": statement.excluded.last_seen_at,
            "resolved_at": None,
        },
    )
    await session.execute(statement)


async def resolve_issue(
    session: AsyncSession,
    *,
    dataset: str,
    scope_id: str,
    kind: str,
    window_start: datetime,
) -> None:
    """缺口已被补上时标记解决（保留历史行，不物理删除）。"""

    issue = await session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.dataset == dataset,
            DataQualityIssue.scope_id == scope_id,
            DataQualityIssue.kind == kind,
            DataQualityIssue.window_start == window_start,
        )
    )
    if issue is not None and issue.resolved_at is None:
        issue.resolved_at = datetime.now(tz=UTC)


async def list_issues(
    session: AsyncSession,
    *,
    dataset: str | None = None,
    scope_id: str | None = None,
    kind: str | None = None,
    unresolved_only: bool = False,
    limit: int = 50,
    cursor: int | None = None,
) -> tuple[list[DataQualityIssue], int | None]:
    """按 id 升序的游标分页。"""

    statement = select(DataQualityIssue).order_by(DataQualityIssue.id).limit(limit + 1)
    if dataset:
        statement = statement.where(DataQualityIssue.dataset == dataset)
    if scope_id:
        statement = statement.where(DataQualityIssue.scope_id == scope_id)
    if kind:
        statement = statement.where(DataQualityIssue.kind == kind)
    if unresolved_only:
        statement = statement.where(DataQualityIssue.resolved_at.is_(None))
    if cursor is not None:
        statement = statement.where(DataQualityIssue.id > cursor)
    rows = list(await session.scalars(statement))
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


def detect_price_jumps(rows: Sequence[CandleRow], threshold_ratio: float = 0.2) -> list[Outlier]:
    """相邻收盘价涨跌幅超过阈值即视为异常跳变（拆股/脏数据排查用）。"""

    ordered = sorted(rows, key=lambda row: row.open_time)
    outliers: list[Outlier] = []
    for previous, current in pairwise(ordered):
        if previous.close == 0:
            continue
        ratio = float(current.close / previous.close - 1)
        if abs(ratio) > threshold_ratio:
            outliers.append(
                Outlier(
                    open_time=current.open_time,
                    previous_close=previous.close,
                    close=current.close,
                    ratio=ratio,
                )
            )
    return outliers


def is_stale(latest: datetime | None, now: datetime, bar_seconds: int) -> bool:
    """最新一根 K 线是否已超过「周期 × 3」未更新（采集停摆判定）。"""

    if latest is None:
        return True
    max_age = timedelta(seconds=max(bar_seconds * 3, 60))
    return now - latest > max_age
