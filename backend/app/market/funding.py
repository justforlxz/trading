"""资金费历史采集：从 OKX 公开接口回溯落库。

资金费是永续合约独有的结算现金流，现货没有这项数据，因此本模块只采集 SWAP。
上游分页方向与 K 线一致：`after=<毫秒时间戳>` 返回严格早于该时刻的记录，所以回溯
游标始终取「本页最早的 fundingTime」，不使用反方向的 `before`。

能回溯多深由上游保留的历史决定（老标的可能只有几个月），遇到空页即停：本模块不
补造费率，覆盖率由结算环节按实际记录报。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from app.core import UpstreamError, ValidationError, utc_from_millis
from app.db import session_scope
from app.exchange import OkxClient
from app.market.candles import dedupe_sorted
from app.market.model import Funding, to_epoch

# 上游的资金费历史端点；公开接口，无需鉴权。
FUNDING_PATH = "/api/v5/public/funding-rate-history"

# 上游单次请求的上限；`page_limit` 不得超过它。
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = MAX_PAGE_LIMIT

# 单条 INSERT 的批量上限：每行 5 个绑定值，1000 行远低于 PostgreSQL 的绑定参数上限。
UPSERT_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class FundingPoint:
    """一个结算时刻的资金费率。

    两档费率都可能为空：上游空串/null 是「没有这个值」，`"0"` 是「费率确实为 0」，
    两种事实不能混为一谈。
    """

    inst_id: str
    funding_time: datetime
    funding_rate: Decimal | None
    realized_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class FundingUpsertResult:
    """一次幂等写入的结果。"""

    inserted: int
    updated: int


@dataclass(frozen=True, slots=True)
class FundingSyncResult:
    """一次回溯采集的结果：翻了多少页、下载多少、写入了多少。"""

    inst_id: str
    downloaded: int
    inserted: int
    updated: int
    pages: int


def parse_funding_rows(rows: Iterable[Any], inst_id: str) -> list[FundingPoint]:
    """上游行 → 费率点，按结算时刻升序且同一时刻只保留最后一条。

    纯函数：不发请求、不落库，已知输入对应确定的输出，可直接断言。
    """

    points = [_parse_row(row, inst_id) for row in rows]
    return dedupe_sorted(points, key=lambda point: point.funding_time)


def fetch_funding_page(
    client: OkxClient,
    inst_id: str,
    *,
    after: datetime | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> list[FundingPoint]:
    """取一页资金费；`after` 指向更早的一段（不含该时刻本身）。"""

    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValidationError(f"limit 必须在 1..{MAX_PAGE_LIMIT} 之间")
    params: dict[str, Any] = {"instId": inst_id, "limit": str(limit)}
    if after is not None:
        if after.tzinfo is None:
            raise ValidationError("after 必须是带时区的时间")
        params["after"] = str(round(after.timestamp() * 1000))
    return parse_funding_rows(client.get(FUNDING_PATH, params), inst_id)


def backfill_funding(
    client: OkxClient,
    inst_id: str,
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
) -> FundingSyncResult:
    """从最新一页起持续回溯到该标的最早记录，并幂等落库。

    终止条件是上游返回空页，不是固定页数：历史深度由标的上市时间决定。
    游标只取本页最早的 `fundingTime`，因此相邻两页不重叠、不跳页；
    上游若忽略游标，游标不前进也会终止，避免死循环。
    """

    if not 1 <= page_limit <= MAX_PAGE_LIMIT:
        raise ValidationError(f"page_limit 必须在 1..{MAX_PAGE_LIMIT} 之间")

    collected: list[FundingPoint] = []
    cursor: datetime | None = None
    pages = 0
    while True:
        page = fetch_funding_page(client, inst_id, after=cursor, limit=page_limit)
        if not page:
            break
        pages += 1
        collected.extend(page)
        earliest = page[0].funding_time
        if cursor is not None and earliest >= cursor:
            break
        cursor = earliest

    points = dedupe_sorted(collected, key=lambda point: point.funding_time)
    written = upsert_funding(points)
    return FundingSyncResult(
        inst_id=inst_id,
        downloaded=len(points),
        inserted=written.inserted,
        updated=written.updated,
        pages=pages,
    )


def upsert_funding(points: Iterable[FundingPoint]) -> FundingUpsertResult:
    """批量幂等写入：同一 `(inst_id, funding_time)` 重复写只覆盖费率。

    写入按固定行数切块，避免深回溯一次撞上 PostgreSQL 的绑定参数上限；
    同一批内的重复结算时刻先合并，计数只按唯一键算。
    """

    prepared: dict[tuple[str, int], dict[str, Any]] = {}
    for point in points:
        row = Funding.from_point(point)
        prepared[(row.inst_id, row.funding_time)] = {
            "inst_id": row.inst_id,
            "funding_time": row.funding_time,
            "funding_rate": row.funding_rate,
            "realized_rate": row.realized_rate,
            "updated_at": row.updated_at,
        }
    if not prepared:
        return FundingUpsertResult(inserted=0, updated=0)

    rows = list(prepared.values())
    existing: set[tuple[str, int]] = set()
    with session_scope() as session:
        for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
            batch = rows[offset : offset + UPSERT_BATCH_SIZE]
            existing |= _existing_keys(session, batch)
            statement = postgresql_insert(Funding).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=["inst_id", "funding_time"],
                set_={
                    "funding_rate": statement.excluded.funding_rate,
                    "realized_rate": statement.excluded.realized_rate,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            session.execute(statement)

    return FundingUpsertResult(
        inserted=len(prepared) - len(existing),
        updated=len(existing),
    )


def load_funding(
    inst_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[FundingPoint]:
    """按 `funding_time` 升序读出资金费；`start`/`end` 为半开窗口。"""

    statement = select(Funding).where(Funding.inst_id == inst_id)
    if start is not None:
        statement = statement.where(Funding.funding_time >= to_epoch(start))
    if end is not None:
        statement = statement.where(Funding.funding_time < to_epoch(end))
    statement = statement.order_by(Funding.funding_time)
    with session_scope() as session:
        return [row.to_point() for row in session.scalars(statement)]


def _parse_row(row: Any, inst_id: str) -> FundingPoint:
    """上游单行 → 费率点；结构或数值不合规一律按上游故障上抛。"""

    if not isinstance(row, dict):
        raise UpstreamError(f"资金费数据结构异常:{row!r}")
    try:
        funding_time = utc_from_millis(row["fundingTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamError(f"资金费结算时刻非法:{row!r}") from exc
    return FundingPoint(
        inst_id=inst_id,
        funding_time=funding_time,
        funding_rate=_rate(row.get("fundingRate"), row),
        realized_rate=_rate(row.get("realizedRate"), row),
    )


def _rate(raw: Any, row: Any) -> Decimal | None:
    """费率字段 → `Decimal`；空串与 null 是缺失，不是 0。"""

    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise UpstreamError(f"资金费费率非法:{row!r}") from exc


def _existing_keys(session: Any, batch: Sequence[dict[str, Any]]) -> set[tuple[str, int]]:
    """查出这批行里已经存在的唯一键，用于区分 inserted / updated。"""

    grouped: dict[str, list[int]] = {}
    for row in batch:
        grouped.setdefault(row["inst_id"], []).append(row["funding_time"])
    existing: set[tuple[str, int]] = set()
    for inst_id, funding_times in grouped.items():
        found = session.scalars(
            select(Funding.funding_time).where(
                Funding.inst_id == inst_id,
                Funding.funding_time.in_(funding_times),
            )
        )
        existing.update((inst_id, funding_time) for funding_time in found)
    return existing
